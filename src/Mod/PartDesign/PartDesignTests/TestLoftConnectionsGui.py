# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/loft-connections.md)

"""The loft panel's Connections group, as Onshape's connections: a list of vertex pairs, an "Add
connection" button that takes a vertex on the profile and then its partner on the section, and
"Remove" (or Delete) for the selected rows.

Designed model, the same as TestLoftConnections (oracle facts GB12g): a square 20 at z 0 lofted to a
square 10 turned 45 degrees at z 30. Without connections V 6414.2136; with the corner (10, 10) joined
to (-7.07, 0), a 135 degree twist, V 3585.7864.
"""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestLoftFilletOptionsGui import PanelCase, widget, square
from PartDesignTests.TestDressUpDeleteKeyGui import pump

V = App.Vector
H = 30.0
S = 10 * math.sqrt(0.5)


def turnedSquare(side):
    r = side * math.sqrt(0.5)
    return models.polygon([(r, 0), (0, r), (-r, 0), (0, -r)])


class TestLoftConnectionsGui(PanelCase):
    def loft(self):
        self.document("LoftConnectionsGui")
        self.profile = models.sketch(self.doc, "Bottom", square(20), self.body)
        self.section = models.sketch(self.doc, "Top", turnedSquare(10), self.body, z=H)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.profile
        loft.Sections = [self.section]
        self.activate()
        return loft

    def vertexName(self, sketch, xy):
        for i, vertex in enumerate(sketch.Shape.Vertexes, 1):
            if (vertex.Point - sketch.Placement.multVec(V(xy[0], xy[1], 0))).Length < 1e-6:
                return "Vertex%d" % i
        self.fail("no vertex of %s at %s" % (sketch.Name, xy))

    def pick(self, obj, sub):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.3)

    def rows(self):
        listing = widget(QtWidgets.QListWidget, "listConnections")
        self.assertIsNotNone(listing, "no Connections list")
        return [listing.item(i).text() for i in range(listing.count())]

    def addTwist(self, sectionFirst=False):
        button = widget(QtWidgets.QPushButton, "buttonAddConnection")
        self.assertIsNotNone(button, "no Add connection button")
        button.setChecked(True)
        pump(0.1)
        bottom = (self.profile, self.vertexName(self.profile, (10, 10)))
        top = (self.section, self.vertexName(self.section, (-S, 0)))
        for obj, sub in (top, bottom) if sectionFirst else (bottom, top):
            self.pick(obj, sub)
        self.assertFalse(button.isChecked(), "the button stays down after a pair")
        self.assertEqual(Gui.Selection.getSelectionEx(), [], "the picks stay selected")
        return bottom, top

    def testEmptyListAndButtons(self):
        self.edit(self.loft())
        self.assertEqual(self.rows(), [])
        self.assertIsNotNone(widget(QtWidgets.QPushButton, "buttonAddConnection"))
        self.assertIsNotNone(widget(QtWidgets.QPushButton, "buttonRemoveConnection"))
        self.assertIsNone(widget(QtWidgets.QLabel, "labelConnectionHint"), "a hint shows with nothing to do")

    def testAddAConnectionFromThePanel(self):
        loft = self.loft()
        self.assertAlmostEqual(loft.Shape.Volume, 6414.2136, delta=0.02)
        self.edit(loft)
        bottom, top = self.addTwist()
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("Bottom", self.rows()[0])
        self.assertIn("Top", self.rows()[0])
        self.assertAlmostEqual(loft.Shape.Volume, 3585.7864, delta=0.02)
        self.ok()
        self.assertEqual(loft.Connections, [(self.profile, (bottom[1],)), (self.section, (top[1],))])
        self.assertAlmostEqual(loft.Shape.Volume, 3585.7864, delta=0.02)

    def testSectionPickedFirstIsStoredProfileFirst(self):
        loft = self.loft()
        self.edit(loft)
        bottom, top = self.addTwist(sectionFirst=True)
        self.ok()
        self.assertEqual(loft.Connections, [(self.profile, (bottom[1],)), (self.section, (top[1],))])

    def testCancelPutsThemBack(self):
        loft = self.loft()
        self.edit(loft)
        self.addTwist()
        self.cancel()
        self.assertEqual(loft.Connections, [])
        self.assertAlmostEqual(loft.Shape.Volume, 6414.2136, delta=0.02)

    def testRemoveTheSelectedRow(self):
        loft = self.loft()
        self.edit(loft)
        self.addTwist()
        listing = widget(QtWidgets.QListWidget, "listConnections")
        listing.item(0).setSelected(True)
        widget(QtWidgets.QPushButton, "buttonRemoveConnection").click()
        pump(0.3)
        self.assertEqual(self.rows(), [])
        self.assertEqual(loft.Connections, [])
        self.assertAlmostEqual(loft.Shape.Volume, 6414.2136, delta=0.02)
        self.ok()

    def testAnEdgePickShowsTheReason(self):
        loft = self.loft()
        self.edit(loft)
        widget(QtWidgets.QPushButton, "buttonAddConnection").setChecked(True)
        pump(0.1)
        self.pick(self.profile, "Edge1")
        hint = widget(QtWidgets.QLabel, "labelConnectionHint")
        self.assertIsNotNone(hint, "no reason shown")
        self.assertIn("vertex of the profile or of the section", hint.text())
        self.assertEqual(self.rows(), [])
        self.assertEqual(loft.Connections, [])


if __name__ == "__main__":
    unittest.main()
