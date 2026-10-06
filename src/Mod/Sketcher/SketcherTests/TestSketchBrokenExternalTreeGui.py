# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch whose external geometry lost its element is flagged in the tree (FreeCAD-CH, ops#144;
upstream PR 32478 for upstream issue 20686, and upstream issue 32102).

Upstream flags the sketch's tree item (an overlay, and the tooltip "Missing external geometry")
when external geometry is marked Missing. Here such a sketch fails before its external geometry
is rebuilt (ops#72), so the flag also follows the broken link ("?Edge2"), and the tooltip names it.
Upstream issue 32102: the source's edge toggled to construction breaks the projection the same way.

Designed geometry: a 20 x 20 x 10 pad whose side at x = 20 is replaced by a V, and two sketches,
one projecting the other's line."""

import FreeCAD
import Part

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase
from SketcherTests.TestSketchMissingExternal import add_lines, edge_between

App = FreeCAD
V = App.Vector
FLAG = "Missing external geometry"

try:
    from PySide import QtWidgets
except ImportError:
    QtWidgets = None


def treeToolTips(obj):
    """The tooltips of obj's items in the tree views."""
    tips = []
    for tree in FreeCADGui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        if tree.metaObject().className() != "Gui::TreeWidget":
            continue
        it = QtWidgets.QTreeWidgetItemIterator(tree)
        while it.value():
            item = it.value()
            if item.text(0) == obj.Label:
                tips.append(item.toolTip(0))
            it += 1
    return tips


class TestSketchBrokenExternalTreeGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = App.newDocument("TestSketchBrokenExternalTreeGui")

    def flagOf(self, sketch):
        self.flush_gui(100)
        tips = treeToolTips(sketch)
        self.assertTrue(tips, "no tree item for " + sketch.Label)
        return tips[0]

    def testMissingPadEdgeFlagged(self):
        """A sketch on XY projects the pad's top edge at x = 20; the edit removes that side."""
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        body = self.doc.addObject("PartDesign::Body", "Body")
        profile = body.newObject("Sketcher::SketchObject", "Profile")
        add_lines(profile, [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Length = 10
        self.doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnRight")
        sketch.AttachmentSupport = [
            ([f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0], "")
        ]
        sketch.MapMode = "FlatFace"
        top = edge_between(pad.Shape, (20, 0, 10), (20, 20, 10))
        sketch.addExternal(pad.Name, top)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertNotIn(FLAG, self.flagOf(sketch))

        profile.delGeometry(1)
        add_lines(profile, [(20, 0), (25, 10), (20, 20)])
        self.doc.recompute()
        self.assertFalse(sketch.isValid())
        self.assertEqual(self.flagOf(sketch), f"{FLAG}: Pad.{top}")

    def testSourceToggledToConstructionFlagged(self):
        """Upstream issue 32102: Dest projects Source's second line (x = 10); toggling that line
        to construction takes it out of Source's shape. Dest fails and is flagged."""
        source = self.doc.addObject("Sketcher::SketchObject", "Source")
        add_lines(source, [(0, 0), (10, 0), (10, 10)])
        self.doc.recompute()
        dest = self.doc.addObject("Sketcher::SketchObject", "Dest")
        dest.Placement = App.Placement(V(0, 0, 5), App.Rotation())
        dest.addExternal("Source", "Edge2")
        dest.addGeometry(Part.Circle(V(10, 5, 0), V(0, 0, 1), 1), False)
        self.doc.recompute()
        self.assertTrue(dest.isValid(), dest.getStatusString())
        self.assertNotIn(FLAG, self.flagOf(dest))

        source.toggleConstruction(1)
        self.doc.recompute()
        self.assertEqual(len(source.Shape.Edges), 1)
        self.assertFalse(dest.isValid())
        self.assertEqual(self.flagOf(dest), f"{FLAG}: Source.Edge2")
        # the flag goes when the link is repaired: the line is defining again
        source.toggleConstruction(1)
        self.doc.recompute()
        self.assertTrue(dest.isValid(), dest.getStatusString())
        self.assertEqual(dest.ExternalGeometry, [(source, ("Edge2",))])
        self.assertNotIn(FLAG, self.flagOf(dest))
