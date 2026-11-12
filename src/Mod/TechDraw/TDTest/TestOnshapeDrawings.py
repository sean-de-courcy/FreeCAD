# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's drawing basics (ops#640: ranks 11 and 10). App tests, no GUI: without the
# GUI a view's hidden-line pass runs in the calling thread, so its edges exist after recompute().

"""Rank 11: a page takes its template's projection, as Onshape's templates carry theirs: an ISO
template is first angle, an ANSI one third angle; a new projection group follows its page.

Rank 10 probe: a dimension on a drawing edge after an edit of the model. Onshape's dimension
follows its edge through edits (topology ids), and when the edge is gone it stays, red and
dangling, with its old value (hands-on E8). The model is an L-shaped plate 5 mm thick in the top
view (a 40 x 20 rectangle less its 15 x 10 upper right corner), its edges by their lengths:
bottom 40, right 10, step 15, inner 10, top 25, left 20."""

import os
import unittest

import FreeCAD
import Part

from .TechDrawTestUtilities import createPageWithSVGTemplate

App = FreeCAD
V = App.Vector

TEMPLATES = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")
ISO_TEMPLATE = os.path.join(TEMPLATES, "ISO", "A4_Landscape_TD.svg")
ANSI_TEMPLATE = os.path.join(TEMPLATES, "ASME", "ANSIA_Landscape.svg")

TOL = 1e-6


def plate(points, thickness=5):
    """A plate of the closed polygon `points` (x, y), `thickness` thick on z = 0."""
    wire = Part.makePolygon([V(x, y, 0) for x, y in points] + [V(*points[0], 0)])
    return Part.Face(wire).extrude(V(0, 0, thickness))


L_PLATE = [(0, 0), (40, 0), (40, 10), (25, 10), (25, 20), (0, 20)]
# the same plate with a 5 x 3 notch in its bottom edge: more edges, the left edge unchanged
NOTCHED = [(0, 0), (15, 0), (15, 3), (20, 3), (20, 0), (40, 0), (40, 10), (25, 10), (25, 20),
           (0, 20)]
# the L filled in: the step (15) and inner (10) edges are gone, the box the same
FILLED = [(0, 0), (40, 0), (40, 20), (0, 20)]
# the lower arm 10 mm longer: the bottom edge 50, the same edge count
STRETCHED = [(0, 0), (50, 0), (50, 10), (25, 10), (25, 20), (0, 20)]


class TestTemplateProjection(unittest.TestCase):
    """Rank 11: ISO first angle, ANSI third angle, whichever order the links are made in."""

    def setUp(self):
        for path in (ISO_TEMPLATE, ANSI_TEMPLATE):
            if not os.path.isfile(path):
                self.skipTest("no template " + path)
        self.doc = App.newDocument("TDTemplateProjection")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def page(self, path, pageFirst=True):
        page = self.doc.addObject("TechDraw::DrawPage", "Page")
        template = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        if pageFirst:
            # the GUI's order (TechDraw_PageTemplate): the page's link, then the file
            page.Template = template
            template.Template = path
        else:
            template.Template = path
            page.Template = template
        return page

    def testIsoIsFirstAngle(self):
        for pageFirst in (True, False):
            ansi = self.page(ANSI_TEMPLATE, pageFirst)
            self.assertEqual(ansi.ProjectionType, "Third angle")
            iso = self.page(ISO_TEMPLATE, pageFirst)
            self.assertEqual(iso.ProjectionType, "First angle")

    def testTemplateChangeFollows(self):
        """Another template on the same page: its projection follows."""
        page = self.page(ISO_TEMPLATE)
        self.assertEqual(page.ProjectionType, "First angle")
        page.Template.Template = ANSI_TEMPLATE
        self.assertEqual(page.ProjectionType, "Third angle")
        page.Template.Template = ISO_TEMPLATE
        self.assertEqual(page.ProjectionType, "First angle")

    def testNewGroupFollowsItsPage(self):
        """A new projection group's projection is the page's ("Default")."""
        page = self.page(ANSI_TEMPLATE)
        box = self.doc.addObject("Part::Box", "Box")
        group = self.doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
        page.addView(group)
        group.Source = [box]
        self.assertEqual(group.ProjectionType, "Default")
        group.addProjection("Front")
        self.doc.recompute()
        self.assertEqual(group.ProjectionType, "Default")


def edgeIndexes(view, length, horizontal):
    """The view's edges of `length` (mm, unscaled) that are horizontal or vertical on the sheet."""
    found = []
    i = 0
    while True:
        try:
            edge = view.getEdgeByIndex(i)
        except ValueError:
            return found
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        along = abs(b.x - a.x) if horizontal else abs(b.y - a.y)
        across = abs(b.y - a.y) if horizontal else abs(b.x - a.x)
        if abs(edge.Length - length) < TOL and abs(along - length) < TOL and across < TOL:
            found.append(i)
        i += 1


class TestDimensionAfterEdit(unittest.TestCase):
    """Rank 10 probe: a top view of the plate on a 1:1 page and a dimension on one edge, then an
    edit of the plate. Each test prints its outcome ("follows", "jumps", "red") for the report."""

    def setUp(self):
        self.doc = App.newDocument("TDDimensionAfterEdit")
        self.model = self.doc.addObject("Part::Feature", "Plate")
        self.model.Shape = plate(L_PLATE)
        self.page = createPageWithSVGTemplate(self.doc)
        self.page.Scale = 1.0
        self.view = self.doc.addObject("TechDraw::DrawViewPart", "View")
        self.page.addView(self.view)
        self.view.Source = [self.model]
        self.view.Direction = V(0, 0, 1)
        self.view.ScaleType = "Custom"
        self.view.Scale = 1.0
        self.doc.recompute()
        self.assertTrue(self.view.getVisibleEdges(), "the view has no edges")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def dimension(self, length, horizontal):
        [index] = edgeIndexes(self.view, length, horizontal)
        dim = self.doc.addObject("TechDraw::DrawViewDimension", "Dimension")
        dim.Type = "Distance"
        dim.MeasureType = "Projected"
        self.page.addView(dim)
        dim.References2D = [(self.view, f"Edge{index}")]
        self.doc.recompute()
        self.assertTrue(dim.isValid(), dim.State)
        self.assertAlmostEqual(dim.getRawValue(), length, delta=TOL)
        return dim, index

    def edit(self, points):
        self.model.Shape = plate(points)
        self.doc.recompute()

    def outcome(self, dim, length, horizontal):
        """What the dimension did: "red" (in error), "follows" (on an edge of `length` in the
        same orientation, with that value), "stale" (its edge index is no longer in the view and
        it keeps its last value, not in error) or "jumps" (on another edge, or another value)."""
        if not dim.isValid():
            return "red"
        sub = dim.References2D[0][1][0]
        index = int(sub[len("Edge"):])
        try:
            self.view.getEdgeByIndex(index)
        except ValueError:
            return "stale"
        onIt = index in edgeIndexes(self.view, length, horizontal)
        value = dim.getRawValue()
        return "follows" if onIt and abs(value - length) < TOL else "jumps"

    def testRenumberedEdgeFollows(self):
        """The notch adds edges; the left edge (20) is the same: the dimension stays on it, by
        its saved geometry (the autocorrect's exact match)."""
        dim, before = self.dimension(20, horizontal=False)
        self.edit(NOTCHED)
        [after] = edgeIndexes(self.view, 20, horizontal=False)
        result = self.outcome(dim, 20, horizontal=False)
        print(f"rank 10 probe, renumbered edge: Edge{before} -> Edge{after}: {result}")
        self.assertEqual(result, "follows")

    def testLengthenedEdgeFollows(self):
        """The bottom edge goes from 40 to 50 with the same edge count: Onshape's dimension
        follows it and reads 50."""
        dim, before = self.dimension(40, horizontal=True)
        self.edit(STRETCHED)
        result = self.outcome(dim, 50, horizontal=True)
        print(f"rank 10 probe, lengthened edge: Edge{before}: {result}")
        self.assertEqual(result, "follows")

    @unittest.expectedFailure
    def testRemovedEdgeGoesRed(self):
        """The L filled in: the step edge (15) is gone. Onshape keeps the dimension, red and
        dangling, with its old value (E8). FreeCAD's autocorrect finds no exact match, its similar
        match isn't written, and the dimension measures whatever edge has the old index now (or
        fails if there is none): the fix is the first rank 10 item after the first modelling
        build (the plan's rank 10 note)."""
        dim, before = self.dimension(15, horizontal=True)
        self.edit(FILLED)
        result = self.outcome(dim, 15, horizontal=True)
        print(f"rank 10 probe, removed edge: Edge{before}: {result}"
              f" (value {dim.getRawValue() if dim.isValid() else 'n/a'})")
        self.assertEqual(result, "red")
        self.assertAlmostEqual(dim.getRawValue(), 15, delta=TOL)


class TestCreateDrawing(unittest.TestCase):
    """Rank 62: Create drawing on the ANSI A template (third angle), No views or a part's
    Suggested views (Top, Front, Right, isometric), no dimensions, the views at the sheet's
    scale, the largest sensible one that fits."""

    def setUp(self):
        if not os.path.isfile(ANSI_TEMPLATE):
            self.skipTest("no template " + ANSI_TEMPLATE)
        import TechDrawCreateDrawing

        self.create = TechDrawCreateDrawing.createDrawing
        self.suggested = set(TechDrawCreateDrawing.SUGGESTED_VIEWS)
        self.doc = App.newDocument("TDCreateDrawing")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self, x, y, z):
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = x, y, z
        self.doc.recompute()
        return box

    def groups(self):
        return self.doc.findObjects(Type="TechDraw::DrawProjGroup")

    def assertAnsiPage(self, page):
        self.assertEqual(os.path.basename(page.Template.Template), "ANSIA_Landscape.svg")
        self.assertEqual(page.ProjectionType, "Third angle")

    def testNoViews(self):
        page = self.create(self.doc, self.box(10, 10, 10), views=False)
        self.assertAnsiPage(page)
        self.assertEqual(self.groups(), [])
        self.assertEqual(page.Views, [])

    def testNoPartNoViews(self):
        """Suggested views with no part (Onshape greys the choice): a page alone."""
        page = self.create(self.doc, None, views=True)
        self.assertAnsiPage(page)
        self.assertEqual(self.groups(), [])

    def testSuggestedViewsFitTheSheet(self):
        """A 170 x 127 x 25 part (Onshape's 6.7 x 5 x 1 in case, 1:3 on its A sheet): four
        views, no dimensions, the sheet's scale below 1:1 and the group following it."""
        page = self.create(self.doc, self.box(170, 127, 25), views=True)
        self.assertAnsiPage(page)
        [group] = self.groups()
        self.assertEqual({view.Type for view in group.Views}, self.suggested)
        self.assertEqual(group.ProjectionType, "Default")
        self.assertEqual(group.ScaleType, "Page")
        self.assertLess(page.Scale, 1.0)
        self.assertGreater(page.Scale, 0.0)
        self.assertAlmostEqual(group.Scale, page.Scale, places=9)
        self.assertEqual(self.doc.findObjects(Type="TechDraw::DrawViewDimension"), [])

    def testSmallPartAtFullSize(self):
        """A 10 mm part fits at 1:1."""
        page = self.create(self.doc, self.box(10, 10, 10), views=True)
        [group] = self.groups()
        self.assertEqual(len(group.Views), 4)
        self.assertAlmostEqual(page.Scale, 1.0, places=9)


def num(value):
    """A property's number, a Quantity's value or a float as it is."""
    return getattr(value, "Value", value)


def viewBox(view, dx=0.0, dy=0.0):
    """The page box (xmin, ymin, xmax, ymax) of a view's visible edges, the view's origin at its
    X, Y plus (dx, dy) (a group's own position for one of its items)."""
    x0, y0 = num(view.X) + dx, num(view.Y) + dy
    boxes = [edge.BoundBox for edge in view.getVisibleEdges(True)]
    if not boxes:
        return None
    return (x0 + min(b.XMin for b in boxes), y0 + min(b.YMin for b in boxes),
            x0 + max(b.XMax for b in boxes), y0 + max(b.YMax for b in boxes))


def groupBox(group):
    """The page box of all of a group's views."""
    boxes = [viewBox(item, num(group.X), num(group.Y)) for item in group.Views]
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def centre(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class TestScaleRefit(unittest.TestCase):
    """Design D, V1 (H1's stumble 2): a change of the sheet's scale keeps each group's middle
    where it was and keeps the group on the sheet when it fits, so the first 2:1 figure does not
    run off it. Onshape's rule for this is unverified (asked of the oracle); the middle is kept."""

    def setUp(self):
        if not os.path.isfile(ANSI_TEMPLATE):
            self.skipTest("no template " + ANSI_TEMPLATE)
        self.doc = App.newDocument("TDScaleRefit")
        self.part = self.doc.addObject("Part::Box", "Part")
        self.part.Length, self.part.Width, self.part.Height = 40, 30, 20
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def group(self, x, y, scale=1.0):
        page = self.doc.addObject("TechDraw::DrawPage", "Page")
        template = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        page.Template = template
        template.Template = ANSI_TEMPLATE
        page.Scale = scale
        group = self.doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
        page.addView(group)
        group.Source = [self.part]
        for name in ("Front", "Top", "Right", "FrontTopRight"):
            group.addProjection(name)
        group.ScaleType = "Page"
        group.X, group.Y = x, y
        self.recompute()
        return page, group

    def recompute(self):
        self.doc.recompute()
        self.doc.recompute()

    def assertOnSheet(self, page, box):
        self.assertGreaterEqual(box[0], -TOL)
        self.assertGreaterEqual(box[1], -TOL)
        self.assertLessEqual(box[2], num(page.PageWidth) + TOL)
        self.assertLessEqual(box[3], num(page.PageHeight) + TOL)

    def testMiddleKept(self):
        """1:1 to 1.5:1 with room around: the group's middle stays, its views larger."""
        page, group = self.group(130, 100)
        before = groupBox(group)
        page.Scale = 1.5
        self.recompute()
        self.assertAlmostEqual(group.Scale, 1.5, places=9)
        after = groupBox(group)
        for a, b in zip(centre(before), centre(after)):
            self.assertAlmostEqual(a, b, delta=0.01)
        self.assertGreater(after[2] - after[0], 1.25 * (before[2] - before[0]))
        self.assertOnSheet(page, after)

    def testKeptOnTheSheet(self):
        """Near the sheet's corner the middle would put the 2:1 group off it: it moves in."""
        page, group = self.group(40, 40)
        page.Scale = 2
        self.recompute()
        self.assertOnSheet(page, groupBox(group))

    def testPositionTypedAfterTheScaleWins(self):
        """A position set after the scale and before the recompute is the user's: kept."""
        page, group = self.group(130, 100)
        page.Scale = 2
        group.X = 150
        self.recompute()
        self.assertAlmostEqual(num(group.X), 150.0, places=6)

    def testCreateDrawingThenTwoToOne(self):
        """H1's stumble 2 as made: Create Drawing's suggested views of the block, then the sheet
        at 2:1: every view stays on the sheet."""
        import TechDrawCreateDrawing

        page = TechDrawCreateDrawing.createDrawing(self.doc, self.part, views=True)
        [group] = self.doc.findObjects(Type="TechDraw::DrawProjGroup")
        page.Scale = 2
        self.recompute()
        self.assertAlmostEqual(group.Scale, 2.0, places=9)
        self.assertOnSheet(page, groupBox(group))
        # inside the sheet's 20 mm border, so inside ANSI A's frame (review V1R-3)
        box = groupBox(group)
        self.assertGreaterEqual(box[0], 20.0 - TOL)
        self.assertGreaterEqual(box[1], 20.0 - TOL)
        self.assertLessEqual(box[2], num(page.PageWidth) - 20.0 + TOL)
        self.assertLessEqual(box[3], num(page.PageHeight) - 20.0 + TOL)

    def testUndoPutsTheGroupBack(self):
        """Review V1R-1: the move is part of the scale's own step, so undo restores both, also
        when the recompute comes after the step (the GUI's order)."""
        self.doc.UndoMode = 1
        page, group = self.group(40, 40)
        self.doc.openTransaction("Sheet scale")
        page.Scale = 2
        self.doc.commitTransaction()
        self.recompute()
        moved = abs(num(group.X) - 40.0) + abs(num(group.Y) - 40.0)
        self.assertGreater(moved, 1e-3)   # moved into the sheet's border
        self.doc.undo()
        self.recompute()
        self.assertAlmostEqual(page.Scale, 1.0, places=9)
        self.assertAlmostEqual(num(group.X), 40.0, places=6)
        self.assertAlmostEqual(num(group.Y), 40.0, places=6)

    def testLockedGroupStays(self):
        """Review V1R-2: a locked group keeps its place."""
        page, group = self.group(40, 40)
        group.LockPosition = True
        page.Scale = 2
        self.recompute()
        self.assertAlmostEqual(num(group.X), 40.0, places=6)
        self.assertAlmostEqual(num(group.Y), 40.0, places=6)

    def testFreeViewKeepsItsRow(self):
        """Reviews V1R-4, V1R-6 and V1R-7: with a free view on the sheet (one on the Right view's
        row, as Project View places it) the group is not refitted: it keeps its place, so the free
        view stays on its row and no other view moves, as before V1."""
        page, group = self.group(90, 100)
        right = [v for v in group.Views if v.Type == "Right"][0]
        rx, ry = num(group.X) + num(right.X), num(group.Y) + num(right.Y)
        free = self.doc.addObject("TechDraw::DrawProjGroupItem", "View")
        page.addView(free)
        free.Source = [self.part]
        free.Direction = V(0, 1, 0)
        free.XDirection = V(-1, 0, 0)
        free.ScaleType = "Page"
        free.X, free.Y = rx + 70, ry
        self.recompute()
        page.Scale = 2
        self.recompute()
        self.assertAlmostEqual(num(group.X), 90.0, places=6)
        self.assertAlmostEqual(num(group.Y), 100.0, places=6)
        self.assertAlmostEqual(num(free.X), rx + 70, places=6)
        self.assertAlmostEqual(num(free.Y), num(group.Y) + num(right.Y), places=6)

    def testNoRefitWhileNotKeptUpdated(self):
        """Review V1R-5: with the sheet's updates off the views' geometry is not at the old scale,
        so no refit is guessed: the group keeps its place."""
        page, group = self.group(90, 100)
        page.KeepUpdated = False
        page.Scale = 2
        page.Scale = 4
        self.recompute()
        self.assertAlmostEqual(num(group.X), 90.0, places=6)
        self.assertAlmostEqual(num(group.Y), 100.0, places=6)

# ---- V1's GUI: Insert View, Project View, the sheet's scale (design D, ops#640) -------------------

def designedBlock(doc):
    """The designed block (design D, section 5): 40 x 30 x 20, a through hole d 10 along the 20
    at (20, 15), a pocket 10 x 10 x 8 deep in the top at x 2..12, y 10..20 (clear of the hole)."""
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = "Block"
    xy = [o for o in body.Origin.OriginFeatures if o.Role == "XY_Plane"][0]

    def sketch(name, offset=0.0):
        sk = body.newObject("Sketcher::SketchObject", name)
        sk.AttachmentSupport = [(xy, "")]
        sk.MapMode = "FlatFace"
        sk.AttachmentOffset = App.Placement(V(0, 0, offset), App.Rotation())
        return sk

    def rect(sk, x0, y0, x1, y1):
        p = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        for a, b in zip(p, p[1:] + p[:1]):
            sk.addGeometry(Part.LineSegment(a, b), False)

    base = sketch("Base")
    rect(base, 0, 0, 40, 30)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = base
    pad.Length = 20
    doc.recompute()
    circle = sketch("HoleSketch")
    circle.addGeometry(Part.Circle(V(20, 15, 0), V(0, 0, 1), 5), False)
    hole = body.newObject("PartDesign::Pocket", "Hole")
    hole.Profile = circle
    hole.Type = 1  # through all
    hole.Midplane = True
    doc.recompute()
    top = sketch("PocketSketch", 20)
    rect(top, 2, 10, 12, 20)
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = top
    pocket.Length = 8
    doc.recompute()
    return body


if App.GuiUp:
    import time

    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    def pump(seconds=0.2):
        app = QtWidgets.QApplication.instance()
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def waitFor(condition, seconds=30.0):
        """Pumps events until `condition()` holds; whether it did."""
        end = time.time() + seconds
        while time.time() < end:
            if condition():
                return True
            pump(0.05)
        return condition()

    def rezFactor():
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Rez")
        return group.GetFloat("Resolution", 10.0)

    def onModal(action):
        """Runs `action(dialog)` on the next modal dialog that opens."""

        def find():
            dialog = QtWidgets.QApplication.activeModalWidget()
            if dialog is None:
                QtCore.QTimer.singleShot(50, find)
                return
            action(dialog)

        QtCore.QTimer.singleShot(50, find)


@unittest.skipUnless(App.GuiUp, "the GUI's commands")
class TestDrawingViewsGui(unittest.TestCase):
    """Design D, slice V1: Insert View lists the document's parts (never a file browser), asks the
    orientation and scale, and one click places the view; Project View: click a view, move,
    click; the sheet's scale in the page's context menu. Synthetic clicks on the page's view."""

    def setUp(self):
        if not os.path.isfile(ANSI_TEMPLATE):
            self.skipTest("no template " + ANSI_TEMPLATE)
        import TechDrawCreateDrawing

        self.doc = App.newDocument("TDViewsGui")
        pump(0.2)
        self.block = designedBlock(self.doc)
        self.page = TechDrawCreateDrawing.createDrawing(self.doc, None, views=False)
        self.page.ViewObject.show()
        pump(0.5)
        self.view = self.pageView()
        self.assertIsNotNone(self.view, "the page's window is not open")
        Gui.Selection.clearSelection()

    def tearDown(self):
        if self.view is not None:
            self.key(QtCore.Qt.Key_Escape)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump(0.2)
        App.closeDocument(self.doc.Name)
        pump(0.2)

    # -- the page's view and synthetic input ------------------------------------------------------
    def pageView(self):
        views = [v for v in Gui.getMainWindow().findChildren(QtWidgets.QGraphicsView)
                 if v.isVisible() and v.scene() is not None]
        return views[-1] if views else None

    def at(self, x, y):
        """The viewport pixel of page point (x, y) mm."""
        rez = rezFactor()
        return self.view.mapFromScene(QtCore.QPointF(x * rez, -y * rez))

    def mouse(self, kind, x, y, button=None):
        button = QtCore.Qt.LeftButton if button is None else button
        local = QtCore.QPointF(self.at(x, y))
        viewport = self.view.viewport()
        world = QtCore.QPointF(viewport.mapToGlobal(local.toPoint()))
        if kind == "move":
            event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, local, world, QtCore.Qt.NoButton,
                                      QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        else:
            etype = QtCore.QEvent.MouseButtonPress if kind == "press" else QtCore.QEvent.MouseButtonRelease
            buttons = button if kind == "press" else QtCore.Qt.NoButton
            event = QtGui.QMouseEvent(etype, local, world, button, buttons, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump(0.05)

    def click(self, x, y):
        self.mouse("move", x, y)
        self.mouse("press", x, y)
        self.mouse("release", x, y)

    def moveTo(self, x0, y0, x1, y1, steps=5):
        for i in range(1, steps + 1):
            t = i / steps
            self.mouse("move", x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    def key(self, code):
        for etype in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(
                self.view, QtGui.QKeyEvent(etype, code, QtCore.Qt.NoModifier))
        pump(0.05)

    # -- the dialog ---------------------------------------------------------------------------------
    def insertView(self, source="Block", orientation="Front", scale="2:1", seen=None):
        """Runs Insert View; on its dialog picks `source`, `orientation` and `scale` and accepts
        (None: cancels). `seen` gets the dialog's lists."""

        def answer(dialog):
            sources = dialog.findChild(QtWidgets.QListWidget, "sources")
            orient = dialog.findChild(QtWidgets.QComboBox, "orientation")
            scales = dialog.findChild(QtWidgets.QComboBox, "scale")
            if seen is not None:
                seen["title"] = dialog.objectName()
                seen["sources"] = [sources.item(i).text() for i in range(sources.count())] if sources else None
                seen["current"] = sources.currentItem().text() if sources and sources.currentItem() else None
                seen["orientations"] = [orient.itemText(i) for i in range(orient.count())] if orient else None
            if source is None or not (sources and orient and scales):
                dialog.reject()
                return
            for i in range(sources.count()):
                if sources.item(i).text().startswith(source):
                    sources.setCurrentRow(i)
                    break
            orient.setCurrentIndex(orient.findText(orientation))
            scales.setCurrentIndex(scales.findText(scale))
            dialog.accept()

        onModal(answer)
        Gui.runCommand("TechDraw_View")
        pump(0.3)

    def groups(self):
        return self.doc.findObjects(Type="TechDraw::DrawProjGroup")

    def item(self, group, name):
        found = [v for v in group.Views if v.Type == name]
        return found[0] if found else None

    def settled(self, views):
        return waitFor(lambda: all(v.getVisibleEdges() for v in views))

    def placeFront(self, x=90.0, y=120.0):
        """Insert View of the block, Front at 2:1, placed at (x, y): the new group."""
        self.insertView()
        self.click(x, y)
        pump(0.3)
        [group] = self.groups()
        return group

    # -- the tests ----------------------------------------------------------------------------------
    def testInsertViewListsTheBlock(self):
        """Nothing selected: the dialog (no file browser) lists the block, with the orientations;
        Cancel makes nothing."""
        seen = {}
        self.insertView(source=None, seen=seen)
        self.assertEqual(seen.get("title"), "FreeCADCH_InsertView")
        self.assertTrue(any(s.startswith("Block") for s in seen["sources"]), seen)
        for name in ("Front", "Top", "Right", "Isometric"):
            self.assertIn(name, seen["orientations"])
        self.assertEqual(self.groups(), [])
        self.assertEqual(self.page.Views, [])

    def testOneClickPlacesTheView(self):
        """The click places a group whose front view is the block's front, at 2:1, where clicked;
        no task panel stays open."""
        group = self.placeFront(90, 120)
        anchor = group.Anchor
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor.Type, "Front")
        d = anchor.Direction
        self.assertAlmostEqual(d.y, -1.0, places=6)
        self.assertAlmostEqual(num(group.X), 90.0, delta=0.5)
        self.assertAlmostEqual(num(group.Y), 120.0, delta=0.5)
        self.assertAlmostEqual(group.Scale, 2.0, places=9)
        self.assertFalse(Gui.Control.activeDialog())

    def testProjectRightAndTopFromTheFront(self):
        """After the placing click the projection follows the cursor: to the right a Right view,
        above a Top view, both in the group and aligned. The block defines the edges: the right
        view is the 30 x 20 outline (60 x 40 at 2:1) with no hole edge (the hole's two lines are
        hidden), the top view holds the hole's circle (r 10 at 2:1) and the pocket's square."""
        group = self.placeFront(90, 120)
        self.moveTo(90, 120, 170, 120)
        self.click(170, 120)
        self.moveTo(170, 120, 90, 190)
        self.click(90, 190)
        self.key(QtCore.Qt.Key_Escape)
        right, top = self.item(group, "Right"), self.item(group, "Top")
        self.assertIsNotNone(right, [v.Type for v in group.Views])
        self.assertIsNotNone(top, [v.Type for v in group.Views])
        self.assertTrue(self.settled([group.Anchor, right, top]))
        self.assertAlmostEqual(num(right.Y), 0.0, places=6)   # aligned with the front
        self.assertAlmostEqual(num(top.X), 0.0, places=6)
        self.assertGreater(num(right.X), 0.0)
        self.assertGreater(num(top.Y), 0.0)

        edges = right.getVisibleEdges(True)
        described = [(type(e.Curve).__name__, round(e.Length, 3)) for e in edges]
        self.assertTrue(all(isinstance(e.Curve, (Part.Line, Part.LineSegment)) for e in edges), described)
        box = viewBox(right, -num(right.X), -num(right.Y))
        self.assertAlmostEqual(box[2] - box[0], 60.0, delta=0.01)
        self.assertAlmostEqual(box[3] - box[1], 40.0, delta=0.01)
        # the hole's two lines (and the pocket's walls) are hidden: every upright edge of the right
        # view is a side of its outline, none inside it
        for e in edges:
            bb = e.BoundBox
            if bb.XLength < 1e-6:
                self.assertTrue(abs(bb.XMin - box[0]) < 1e-6 or abs(bb.XMin - box[2]) < 1e-6, described)

        topEdges = top.getVisibleEdges(True)
        circles = [e for e in topEdges if isinstance(e.Curve, Part.Circle)]
        self.assertTrue(circles)
        self.assertTrue(all(abs(e.Curve.Radius - 10.0) < 1e-6 for e in circles))
        lines = [e for e in topEdges if not isinstance(e.Curve, Part.Circle)]
        self.assertGreaterEqual(len(lines), 8)   # the outline and the pocket's square

    def testDiagonalGivesAnIsometric(self):
        group = self.placeFront(90, 120)
        self.moveTo(90, 120, 170, 190)
        self.click(170, 190)
        self.key(QtCore.Qt.Key_Escape)
        self.assertIsNotNone(self.item(group, "FrontTopRight"), [v.Type for v in group.Views])

    def testProjectFromAnotherViewIsFree(self):
        """Project View from a view that is not a group's front view: a free view in the projected
        direction (right of the Right view: the Back view), on the parent's row."""
        group = self.placeFront(70, 120)
        self.moveTo(70, 120, 140, 120)
        self.click(140, 120)
        self.key(QtCore.Qt.Key_Escape)
        right = self.item(group, "Right")
        self.assertIsNotNone(right)
        self.assertTrue(self.settled([right]))
        rx, ry = num(group.X) + num(right.X), num(group.Y) + num(right.Y)
        before = set(o.Name for o in self.doc.Objects)
        Gui.Selection.clearSelection()
        Gui.runCommand("TechDraw_ProjectView")
        pump(0.2)
        self.click(rx, ry)
        self.moveTo(rx, ry, rx + 70, ry)
        self.click(rx + 70, ry)
        self.key(QtCore.Qt.Key_Escape)
        new = [o for o in self.doc.Objects if o.Name not in before and o.isDerivedFrom("TechDraw::DrawViewPart")]
        self.assertEqual(len(new), 1, [o.Name for o in new])
        free = new[0]
        self.assertNotIn(free, group.Views)
        self.assertIn(free, self.page.Views)
        self.assertAlmostEqual(free.Direction.y, 1.0, places=6)
        self.assertAlmostEqual(num(free.Y), ry, delta=0.01)
        self.assertGreater(num(free.X), rx)

    def testInsertViewWithThePartSelected(self):
        """The part selected: the dialog has it current; afterwards no task panel is open and no
        lone second front view is made (H1's stumble 3)."""
        Gui.Selection.addSelection(self.doc.Name, self.block.Name)
        seen = {}
        self.insertView(seen=seen)
        self.assertTrue(seen["current"] and seen["current"].startswith("Block"), seen)
        self.click(100, 120)
        self.key(QtCore.Qt.Key_Escape)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertEqual(len(self.groups()), 1)
        lone = [v for v in self.page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        self.assertEqual(lone, [])

    def testSheetScaleInTheContextMenu(self):
        """The page's context menu holds the sheet's scale; 2:1 sets it."""
        found = {}

        def pick():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                QtCore.QTimer.singleShot(50, pick)
                return
            for action in menu.actions():
                sub = action.menu()
                if sub is not None and sub.objectName() == "FreeCADCH_SheetScale":
                    found["items"] = [a.text() for a in sub.actions()]
                    for a in sub.actions():
                        if a.text() == "2:1":
                            a.trigger()
            menu.close()

        QtCore.QTimer.singleShot(50, pick)
        pos = self.at(20, 20)
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, self.view.viewport().mapToGlobal(pos))
        Gui.Selection.clearSelection()
        # an empty spot of the page: the event goes on to the page's window, whose menu it is
        QtWidgets.QApplication.sendEvent(self.view.viewport(), event)
        pump(0.5)
        self.assertIn("2:1", found.get("items", []), found)
        self.assertAlmostEqual(self.page.Scale, 2.0, places=9)


if __name__ == "__main__":
    unittest.main()
