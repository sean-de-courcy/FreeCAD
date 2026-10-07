# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Parked projections marked in the sketch editor (FreeCAD-CH ops#131 PR B, PLAN decision 21;
notes/reorder-park-projections.md section 4).

A drop to the top of a Body parks a sketch's projection of a later solid in place: the geometry
stays, its link is set aside. In the sketch editor such geometry has its own colour (preference
`ParkedExternalColor`) and the Elements list names what it was projected from,
"(parked: <object>.<element>)". Moved back, it is ordinary external geometry again.

The model is TestBodyReorder's RO11: a 20 x 20 x 10 block, a 10 x 10 x 5 pad on it, and a sketch
at z = 15 projecting the pad's front top edge (y = 5), with a pocket of it. Off screen:
QT_QPA_PLATFORM=offscreen (notes/build.md)."""

import re
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models

V = App.Vector
TOL = 1e-6

VIEW = "User parameter:BaseApp/Preferences/View"
ELEMENTS = "User parameter:BaseApp/Preferences/Mod/Sketcher/Elements"
# Test colours (0xRRGGBBAA), unlike any other of the editor's
EXTERNAL = 0x113355FF
PARKED = 0x557711FF


def processEvents(seconds=0.0):
    end = time.monotonic() + seconds
    while True:
        QtGui.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    """Pumps events until condition() holds, or the timeout passes (instead of fixed waits, which
    pass for nothing on a slow machine)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        processEvents(0.05)
    return bool(condition())


def rgb(packed):
    return tuple(((packed >> shift) & 0xFF) / 255.0 for shift in (24, 16, 8))


def edgeWhere(shape, test):
    found = [i + 1 for i, e in enumerate(shape.Edges) if test(e)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} edges match, expected one")
    return f"Edge{found[0]}"


class TestParkedMarkingGui(unittest.TestCase):
    def setUp(self):
        if not App.GuiUp or Gui.getMainWindow() is None:
            self.skipTest("Requires the GUI")
        self.saved = []
        self.setParameter(VIEW, "ExternalColor", EXTERNAL, unsigned=True)
        self.setParameter(VIEW, "ExternalDefiningColor", EXTERNAL, unsigned=True)
        self.setParameter(VIEW, "ParkedExternalColor", PARKED, unsigned=True)
        self.doc = models.newDocument("ParkedMarkingGui")
        if hasattr(self.doc, "HistoryAlgorithm"):
            self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = False
        self.doc.InternNames = False
        self.body = models.body(self.doc)

    def tearDown(self):
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            self.close()
        for name in list(App.listDocuments()):
            if name.startswith("ParkedMarkingGui"):
                App.closeDocument(name)
        for group, name, old, unsigned in reversed(self.saved):
            grp = App.ParamGet(group)
            if old is None:
                (grp.RemUnsigned if unsigned else grp.RemBool)(name)
            else:
                (grp.SetUnsigned if unsigned else grp.SetBool)(name, old)

    def setParameter(self, group, name, value, unsigned=False):
        grp = App.ParamGet(group)
        names = grp.GetUnsigneds() if unsigned else grp.GetBools()
        old = None
        if name in names:
            old = grp.GetUnsigned(name) if unsigned else grp.GetBool(name)
        self.saved.append((group, name, old, unsigned))
        (grp.SetUnsigned if unsigned else grp.SetBool)(name, value)

    # -- the model (TestBodyReorder.projecting) ---------------------------------------------------

    def projecting(self):
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        block = models.pad(self.body, sketch, 10, "Block")
        sketch = models.sketch(
            self.doc, "Pad2Sketch", models.rectangle(5, 5, 15, 15), self.body, z=10
        )
        pad2 = models.pad(self.body, sketch, 5, "Pad2")
        self.doc.recompute()
        edge = edgeWhere(
            pad2.Shape,
            lambda e: isinstance(e.Curve, Part.Line)
            and all(abs(v.Point.y - 5) < TOL and abs(v.Point.z - 15) < TOL for v in e.Vertexes),
        )
        sketch = models.sketch(
            self.doc, "Projecting", [models.circle(10, 10, 1)], self.body, z=15
        )
        sketch.addExternal(pad2.Name, edge)
        hole = models.pocket(self.body, sketch, 1, "ProjectedHole")
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        return block, pad2, sketch, hole, edge

    def park(self, hole):
        self.body.reorderObject([hole], None, True)
        self.doc.recompute()

    # -- the editor --------------------------------------------------------------------------------

    def edit(self, sketch):
        Gui.ActiveDocument.setEdit(sketch.Name)
        self.assertTrue(
            waitFor(lambda: self.elementsList() is not None and len(self.lineLabels()) == 1),
            "the Elements list",
        )
        self.assertTrue(waitFor(lambda: self.colours("CurvesMaterials")), "the editor's scene")

    def close(self):
        Gui.ActiveDocument.resetEdit()
        self.assertTrue(waitFor(lambda: not Gui.ActiveDocument.getInEdit()), "still in edit")

    def elementsList(self):
        return Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listWidgetElements")

    def lineLabels(self):
        """The Elements list's texts of the lines (the circle is the sketch's only other
        element)."""
        widget = self.elementsList()
        if widget is None:
            return []
        # The list's delegate paints each item's label, which the item gives as its accessible text
        role = QtCore.Qt.AccessibleTextRole
        texts = [widget.item(i).data(role) or "" for i in range(widget.count())]
        return [t for t in texts if "Line" in t]

    def colours(self, prefix):
        """Every colour of the edit-mode materials whose name starts with prefix
        (`CurvesMaterials`, `PointsMaterials_`)."""
        from pivy import coin

        view = Gui.ActiveDocument.ActiveView
        root = view.getViewer().getSoRenderManager().getSceneGraph()
        search = coin.SoSearchAction()
        search.setType(coin.SoMaterial.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(root)
        found = []
        for path in search.getPaths():
            node = path.getTail()
            if node.getName().getString().startswith(prefix):
                found += [tuple(c.getValue()) for c in node.diffuseColor.getValues()]
        return found

    def count(self, colours, packed):
        want = rgb(packed)
        return sum(1 for c in colours if all(abs(a - b) < 1e-3 for a, b in zip(c, want)))

    def marked(self):
        """The colours of the projected line and its end points: parked, external."""
        curves = self.colours("CurvesMaterials")
        points = self.colours("PointsMaterials_")
        return (
            (self.count(curves, PARKED), self.count(curves, EXTERNAL)),
            (self.count(points, PARKED), self.count(points, EXTERNAL)),
        )

    def assertMarked(self, parked):
        """The projected line (two end points, nothing on them) in the parked colour, or in the
        external one; the editor redraws after events, so this waits for it."""
        want = ((1, 0), (2, 0)) if parked else ((0, 1), (0, 2))
        waitFor(lambda: self.marked() == want)
        curves = self.colours("CurvesMaterials")
        points = self.colours("PointsMaterials_")
        self.assertEqual(
            (self.count(curves, PARKED), self.count(curves, EXTERNAL)),
            (1, 0) if parked else (0, 1),
        )
        self.assertEqual(
            (self.count(points, PARKED), self.count(points, EXTERNAL)),
            (2, 0) if parked else (0, 2),
        )

    def assertLabel(self, mark):
        """The line's one label ends with mark, or, with mark None, has no parked mark."""

        def shown():
            labels = self.lineLabels()
            if len(labels) != 1:
                return False
            return labels[0].endswith(mark) if mark else "parked" not in labels[0]

        waitFor(shown)
        labels = self.lineLabels()
        self.assertEqual(len(labels), 1)
        if mark:
            self.assertTrue(labels[0].endswith(mark), labels[0])
        else:
            self.assertNotIn("parked", labels[0])

    def assertExtendedLabel(self, reference):
        """The line's one label, "Line(ExternalEdge1#ID-3, <reference>)", with "#VL<n>" after
        the ID when the sketch has several visual layers."""
        pattern = r"Line\(ExternalEdge1#ID-3(#VL\d+)?, " + re.escape(reference) + r"\)"
        waitFor(lambda: any(re.match("^" + pattern + "$", t) for t in self.lineLabels()))
        labels = self.lineLabels()
        self.assertEqual(len(labels), 1)
        self.assertRegex(labels[0], "^" + pattern + "$")

    # -- the tests ---------------------------------------------------------------------------------

    def testParkedProjectionIsMarked(self):
        """Parked by a top drop: the line keeps its place in the list with
        "(parked: Pad2.<edge>)" and has the parked colour. Moved back below Pad2: plain external
        geometry, in the external colour, without the mark."""
        self.setParameter(ELEMENTS, "ExtendedNaming", False)
        block, pad2, sketch, hole, edge = self.projecting()
        self.edit(sketch)
        self.assertMarked(parked=False)
        self.assertEqual(len(self.lineLabels()), 1)
        self.assertNotIn("parked", self.lineLabels()[0])
        self.close()

        self.park(hole)
        self.assertEqual(sketch.ExternalGeometry, [])
        self.edit(sketch)
        labels = self.lineLabels()
        self.assertEqual(len(labels), 1)
        self.assertTrue(labels[0].endswith(f" (parked: Pad2.{edge})"), labels[0])
        self.assertMarked(parked=True)
        self.close()

        self.body.reorderObject([hole], pad2, True)
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.edit(sketch)
        self.assertNotIn("parked", self.lineLabels()[0])
        self.assertMarked(parked=False)

    def testParkedLabelWithExtendedNaming(self):
        """With the list's extended naming the mark takes the reference's place:
        "Line(ExternalEdge1#ID-3, parked: Pad2.<edge>)"; moved back,
        "Line(ExternalEdge1#ID-3, Pad2.<edge>)" (the reference as the geometry has it)."""
        self.setParameter(ELEMENTS, "ExtendedNaming", True)
        block, pad2, sketch, hole, edge = self.projecting()
        self.park(hole)
        self.edit(sketch)
        self.assertExtendedLabel(f"parked: Pad2.{edge}")
        self.close()

        self.body.reorderObject([hole], pad2, True)
        self.doc.recompute()
        self.edit(sketch)
        self.assertExtendedLabel(f"Pad2.{edge}")

    def testDeletedTargetStaysParked(self):
        """Pad2 deleted while parked: until the next move the line is still parked, and the mark
        still names Pad2 (decision 21: it becomes a missing reference at the next move)."""
        self.setParameter(ELEMENTS, "ExtendedNaming", False)
        block, pad2, sketch, hole, edge = self.projecting()
        self.park(hole)
        profile = pad2.Profile[0]
        self.body.removeObject(pad2)
        self.doc.removeObject(pad2.Name)
        self.doc.removeObject(profile.Name)
        self.doc.recompute()
        self.edit(sketch)
        self.assertTrue(self.lineLabels()[0].endswith(f" (parked: Pad2.{edge})"))
        self.assertMarked(parked=True)

    def testParkedWhileTheEditorIsOpen(self):
        """Parked, undone, redone and moved back with the sketch open in the editor: the colour
        and the Elements list follow each step (the parked record is written after the geometry
        has been drawn)."""
        self.setParameter(ELEMENTS, "ExtendedNaming", False)
        block, pad2, sketch, hole, edge = self.projecting()
        self.doc.UndoMode = 1
        self.edit(sketch)
        self.assertLabel(None)
        self.assertMarked(parked=False)
        mark = f" (parked: Pad2.{edge})"

        self.doc.openTransaction("Move")
        self.park(hole)
        self.doc.commitTransaction()
        self.assertEqual(sketch.ExternalGeometry, [])
        self.assertTrue(Gui.ActiveDocument.getInEdit())
        self.assertLabel(mark)
        self.assertMarked(parked=True)

        self.doc.undo()
        self.doc.recompute()
        self.assertIs(sketch.ExternalGeometry[0][0], pad2)
        self.assertTrue(Gui.ActiveDocument.getInEdit())
        self.assertLabel(None)
        self.assertMarked(parked=False)

        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(sketch.ExternalGeometry, [])
        self.assertTrue(Gui.ActiveDocument.getInEdit())
        self.assertLabel(mark)
        self.assertMarked(parked=True)

        self.body.reorderObject([hole], pad2, True)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertIs(sketch.ExternalGeometry[0][0], pad2)
        self.assertTrue(Gui.ActiveDocument.getInEdit())
        self.assertLabel(None)
        self.assertMarked(parked=False)
        # What uses the sketch computes once the edit ends
        self.close()
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
