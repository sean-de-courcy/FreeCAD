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


if __name__ == "__main__":
    unittest.main()
