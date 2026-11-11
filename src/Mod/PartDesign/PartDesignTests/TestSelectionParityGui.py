# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection parity with Onshape (FreeCAD-CH, PLAN decision 350; notes/selection-parity.md).

P1: a multi-pick field stays armed for the next pick. A new Extrude's first region decides where
it opens (hands-on check A-1): the move restarts the edit, and the Profile field that took the
pick disarmed with the old dialog, so the second region became a plain selection and the Extrude
kept one region (journey S4b). Onshape's Profile field stays active and each region click adds.

Designed geometry: the Enclosure 40 x 40 x 10 at the origin (ResultBoxGuiCase.enclosure). A sketch
in the Enclosure at z 0 with two regions apart from it: R1 10 x 10 at x 100..110 (100 mm^2) and R2
5 x 10 at x 120..125 (50 mm^2), y 5..15. Neither touches the Enclosure, so the Pad opens New after
its first region; padded 10 (the default length) from both: (100 + 50) x 10 = 1500.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDialogFlowGui import DialogFlowCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestCrossBodyGui import siblingEraPath  # ops#654 list on first use

ENCLOSURE = 16000


def visibleField(name):
    """The task view's visible reference field of that objectName, or None."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    found = [
        widget
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name)
        if widget.metaObject().className() == "PartDesignGui::ReferenceField"
        and widget.isVisible()
    ]
    return found[0] if found else None


def armed(field):
    return field is not None and bool(field.property("armed"))


class TestProfileFieldStaysArmedGui(DialogFlowCase):
    """P1: the Profile field after the first region of a new Extrude."""

    def regionsSketch(self):
        """The two-region sketch in the Enclosure; returns it and its regions' names {R1, R2}."""
        geometry = models.rectangle(100, 5, 110, 15) + models.rectangle(120, 5, 125, 15)
        sk = models.sketch(self.doc, "Regions", geometry, self.body)
        sk.MakeInternals = True
        self.doc.recompute()
        regions = {}
        for i, face in enumerate(sk.InternalShape.Faces):
            for name, area in (("R1", 100), ("R2", 50)):
                if abs(face.Area - area) < 1e-6:
                    regions[name] = "InternalFace%d" % (i + 1)
        self.assertEqual(sorted(regions), ["R1", "R2"], regions)
        return sk, regions

    def pickRegion(self, sk, region):
        """A region picked in the 3D view, through the sketch's part as the view gives it."""
        part = sk.getParentGeoFeatureGroup()
        Gui.Selection.addSelection(self.doc.Name, part.Name, sk.Name + "." + region)
        pump(0.3)

    @siblingEraPath
    def testSecondRegionAfterTheOpeningMoveIsAdded(self):
        """Nothing selected, Pad: its Profile field is armed. R1 picked: the pad and its sketch
        move to a new part (the edit restarts), and the Profile field is armed again. R2 picked:
        the Profile holds both regions, nothing is left selected; OK: the new part 1500, the
        Enclosure 16000."""
        self.enclosure()
        sk, regions = self.regionsSketch()
        bodies = self.bodyNames()
        made = self.newPad()
        self.assertTrue(waitFor(lambda: armed(visibleField("fieldProfile"))), "Profile isn't armed")

        self.pickRegion(sk, regions["R1"])
        self.assertTrue(
            waitFor(lambda: len(self.newBodies(bodies)) == 1),
            "the first region didn't open the pad in a new part",
        )
        [part] = self.newBodies(bodies)
        self.assertTrue(waitFor(lambda: made.getParentGeoFeatureGroup() == part))
        self.waitForPanel()
        self.assertTrue(
            waitFor(lambda: armed(visibleField("fieldProfile"))),
            "the Profile field disarmed after the first region",
        )

        self.pickRegion(sk, regions["R2"])
        self.assertTrue(
            waitFor(lambda: made.Profile is not None and len(made.Profile[1]) == 2),
            "the second region wasn't added: %s" % (made.Profile,),
        )
        self.assertEqual(sorted(made.Profile[1]), sorted([regions["R1"], regions["R2"]]))
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])
        self.assertTrue(armed(visibleField("fieldProfile")))
        self.close(ok=True)
        self.doc.recompute()
        self.assertTrue(made.isValid(), made.getStatusString())
        self.assertAlmostEqual(part.Shape.Volume, 1500, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, ENCLOSURE, places=3)


class TestBoxSelectionGui(unittest.TestCase):
    """P2: a box drawn with the left button in the 3D view, outside dialogs. Onshape (SQ4): right
    to left (crossing) selects every part whose geometry it touches; left to right (window)
    selects a part wholly inside, else the faces and edges wholly inside (no vertices); never
    the Part Studio. The fork gave the studio for a crossing box around one part (journey S1: a part
    counted as touched when its projected bounding box was, and when every part counted, the
    studio replaced them) and for a window around everything (the studio's own bounding box).

    Designed geometry, in the studio: Bar, a body with a 60 x 4 x 4 box turned 45 degrees about
    z at the origin (seen from the top a diagonal strip, 0 <= y - x <= 5.66; its bounding box
    x -2.8..42.4, y 0..45.3); Cube, a body with a 10 mm box at (28, 2, 0): inside Bar's bounding
    box, 11 mm and more from the strip. Top view, except the partial window (isometric)."""

    def setUp(self):
        self.doc = App.newDocument("BoxSelectionGui")
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        self.studio = self.doc.addObject("App::Part", "Studio")
        turned = App.Rotation(App.Vector(0, 0, 1), 45)
        self.bar = self.boxBody("Bar", (60, 4, 4), App.Placement(App.Vector(), turned))
        self.cube = self.boxBody("Cube", (10, 10, 10), App.Placement(App.Vector(28, 2, 0), App.Rotation()))
        self.doc.recompute()
        Gui.Selection.clearSelection()
        self.view = Gui.getDocument(self.doc.Name).ActiveView
        self.viewport = self.view.graphicsView().viewport()
        self.animated = self.view.isAnimationEnabled()
        self.view.setAnimationEnabled(False)
        self.look(self.view.viewTop)

    def tearDown(self):
        self.view.setAnimationEnabled(self.animated)
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump(0.2)

    def boxBody(self, name, size, placement):
        body = self.doc.addObject("PartDesign::Body", name)
        self.studio.addObject(body)
        box = body.newObject("PartDesign::AdditiveBox", name + "Box")
        box.Length, box.Width, box.Height = size
        body.Placement = placement
        return body

    def look(self, direction):
        # A fit right after the new document's recompute fits nothing (the camera stayed at its
        # 4 mm default, off screen and on): let the view take the shapes in first
        pump(0.2)
        direction()
        self.view.fitAll()
        # The fit fills the height only, and a little short: on the portrait viewport off screen
        # (400 x 615) it cut the sides. Zoom out by the aspect and a margin, so every point the
        # tests drag from lies in the viewport.
        width, height = self.view.getSize()
        camera = self.view.getCameraNode()
        camera.height.setValue(camera.height.getValue() * max(1.0, height / width) * 1.3)
        pump(0.4)

    def point(self, x, y, z=5):
        """The viewport point of the world point; it must lie in the viewport (a drag outside it
        is not what a user does, and off screen it selected nothing)."""
        sx, sy = self.view.getPointOnScreen(App.Vector(x, y, z))
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        at = QtCore.QPoint(int(round(sx / scale)), int(round((height - sy - 1) / scale)))
        self.assertTrue(self.viewport.rect().contains(at), "(%g, %g, %g) is off the viewport at %s" % (x, y, z, at))
        return at

    def send(self, kind, at, button, buttons):
        event = QtGui.QMouseEvent(
            kind,
            QtCore.QPointF(at),
            QtCore.QPointF(self.viewport.mapToGlobal(at)),
            button,
            buttons,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(self.viewport, event)

    def drag(self, start, end):
        """A left-button drag on the 3D view from one viewport point to another."""
        left, none = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        self.send(QtCore.QEvent.MouseMove, start, none, none)
        pump(0.1)
        self.send(QtCore.QEvent.MouseButtonPress, start, left, left)
        pump(0.05)
        for i in range(1, 13):
            at = QtCore.QPoint(
                start.x() + (end.x() - start.x()) * i // 12,
                start.y() + (end.y() - start.y()) * i // 12,
            )
            self.send(QtCore.QEvent.MouseMove, at, none, left)
            pump(0.03)
        self.send(QtCore.QEvent.MouseButtonRelease, end, left, none)
        pump(0.5)

    def selected(self):
        """The selection as {"<object>|<body>.<element>"}: "Studio|Cube." is the whole Cube,
        "Studio|" the studio itself."""
        found = set()
        for sel in Gui.Selection.getSelectionEx("", 0):
            for name in sel.SubElementNames or ("",):
                parts = name.split(".")
                short = parts[0] + "." + parts[-1] if len(parts) > 1 else name
                found.add(sel.ObjectName + "|" + short)
        return found

    def whole(self, *bodies):
        return {self.studio.Name + "|" + body.Name + "." for body in bodies}

    def testACrossingBoxAroundOnePartSelectsThatPartOnly(self):
        """Right to left around Cube (x 26..40, y 0..14), inside Bar's bounding box but clear of
        Bar: Cube alone (the fork gave the studio)."""
        self.drag(self.point(40, 0), self.point(26, 14))
        self.assertEqual(self.selected(), self.whole(self.cube))

    def testACrossingBoxTouchingNoGeometrySelectsNothing(self):
        """Right to left over x 10..20, y 30..40: inside Bar's bounding box, 3 mm and more from
        the strip (y - x >= 10 there, the strip ends at 5.66). Nothing (the fork gave Bar, by
        its bounding box)."""
        self.drag(self.point(20, 30), self.point(10, 40))
        self.assertEqual(self.selected(), set())

    def testACrossingBoxOverTheBarSelectsTheBar(self):
        """Right to left over x 18..26, y 18..26, across the strip: Bar."""
        self.drag(self.point(26, 18), self.point(18, 26))
        self.assertEqual(self.selected(), self.whole(self.bar))

    def testAWindowAroundEverythingSelectsBothPartsNotTheStudio(self):
        """Left to right over x -8..48, y -4..50: Bar and Cube (the fork gave the studio)."""
        self.drag(self.point(-8, 50), self.point(48, -4))
        self.assertEqual(self.selected(), self.whole(self.bar, self.cube))

    def testAWindowAroundOnePartSelectsIt(self):
        """Left to right around Cube (x 26..40, y 0..14): Cube; no part of Bar lies inside."""
        self.drag(self.point(26, 14), self.point(40, 0))
        self.assertEqual(self.selected(), self.whole(self.cube))

    def testAWindowOverPartOfAPartSelectsTheElementsWhollyInside(self):
        """Bar hidden, isometric view; a window around the projections of Cube's top face (6 px
        wider): every edge and face of Cube whose vertices all project inside the window (its
        edges are straight and its faces flat, so that is wholly inside); no vertex (Onshape,
        SQ4: a face and its 4 edges), not the whole Cube."""
        self.bar.Visibility = False
        self.look(self.view.viewIsometric)
        shape = self.cube.Shape
        top = [v.Point for v in shape.Vertexes if abs(v.Point.z - 10) < 1e-6]
        self.assertEqual(len(top), 4)
        points = [self.point(p.x, p.y, p.z) for p in top]
        left = min(p.x() for p in points) - 6
        right = max(p.x() for p in points) + 6
        upper = min(p.y() for p in points) - 6
        lower = max(p.y() for p in points) + 6

        def inside(vertex):
            at = self.point(vertex.Point.x, vertex.Point.y, vertex.Point.z)
            margin = min(at.x() - left, right - at.x(), at.y() - upper, lower - at.y())
            self.assertGreaterEqual(abs(margin), 3, "a vertex lies on the window's border")
            return margin > 0

        expected = set()
        kinds = (("Edge", shape.Edges), ("Face", shape.Faces))
        for kind, elements in kinds:
            for i, element in enumerate(elements):
                if all(inside(v) for v in element.Vertexes):
                    expected.add("%s|%s.%s%d" % (self.studio.Name, self.cube.Name, kind, i + 1))
        count = len([v for v in shape.Vertexes if inside(v)])
        self.assertTrue(4 <= count < 8, count)
        self.drag(QtCore.QPoint(left, upper), QtCore.QPoint(right, lower))
        self.assertEqual(self.selected(), expected)
