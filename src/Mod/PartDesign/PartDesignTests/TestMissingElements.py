# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""What a consumer says when its element is gone (FreeCAD-CH ops#69, ops#70, ops#71): the
scenarios of Scenarios/consumers.py, built and edited in V2, and the failing feature's error
message, which should name the missing element."""

import re
import unittest

import FreeCAD as App

from PartDesignTests.Scenarios import consumers


class TestMissingElements(unittest.TestCase):
    def edited(self, scenarioClass):
        """Builds the scenario in V2, records its references' subs, edits and recomputes."""
        scenario = scenarioClass("V2")
        self.addCleanup(scenario.cleanup)
        doc = scenario.newDocument()
        scenario.build(doc)
        doc.recompute()
        for ref in scenario.refs.values():
            owner = doc.getObject(ref.owner)
            self.assertTrue(owner.isValid(), f"{owner.Name}: {owner.getStatusString()}")
        before = {name: self.subs(doc, ref) for name, ref in scenario.refs.items()}
        scenario.edit(doc)
        doc.recompute()
        return doc, scenario, before

    @staticmethod
    def subs(doc, ref):
        value = getattr(doc.getObject(ref.owner), ref.prop)
        if isinstance(value, list):  # Support, Sections: [(object, (subs))]
            return [s for _, subs in value for s in subs]
        return list(value[1])

    def assertFailsNaming(self, owner, *words):
        self.assertFalse(owner.isValid(), f"{owner.Name} stays valid")
        message = owner.getStatusString()
        for word in words:
            self.assertRegex(message, rf"\b{re.escape(word)}\b")
        return message

    def testBinderNamesItsMissingFace(self):
        """Both binders fail, naming the source and the right wall's old name; the left wall,
        still there, isn't named (ops#69)."""
        doc, scenario, before = self.edited(consumers.BinderFacesRemoved)
        [right] = before["binder_right"]
        [left] = [s for s in before["binder_both"] if s != right]
        for name in ("binder_both", "binder_right"):
            message = self.assertFailsNaming(doc.getObject(name), "Slot", right)
            self.assertNotRegex(message, rf"\b{left}\b")

    def testBinderKeepsNoStaleShape(self):
        """The binder of the removed wall alone doesn't keep its old face as if it were valid:
        it fails, and its reference shows the missing marker (ops#69)."""
        doc, _, _ = self.edited(consumers.BinderFacesRemoved)
        binder = doc.getObject("binder_right")
        self.assertFalse(binder.isValid())
        self.assertIn("?", "".join(s for _, subs in binder.Support for s in subs))

    def testHoleNamesItsMissingCircle(self):
        """The hole fails naming the sketch and the second circle's edge (ops#70)."""
        doc, _, before = self.edited(consumers.HoleProfileCircleRemoved)
        self.assertFailsNaming(doc.getObject("Hole"), "HoleSketch", before["hole_profile"][1])

    def testHelixNamesItsMissingCircle(self):
        """The helix fails naming the sketch and the second circle's edge (ops#70)."""
        doc, _, before = self.edited(consumers.HelixProfileCircleRemoved)
        self.assertFailsNaming(doc.getObject("Helix"), "HelixSketch", before["helix_profile"][1])

    def testLoftNamesItsMissingVertex(self):
        """The loft fails naming the sketch and the point's vertex (ops#71)."""
        doc, _, before = self.edited(consumers.LoftToRemovedPoint)
        self.assertFailsNaming(doc.getObject("Feature"), "Points", before["loft_section"][0])

    def testPipeNamesItsMissingSectionVertex(self):
        """The pipe fails naming the sketch and the point's vertex, not with "A fatal error
        occurred when making the pipe" (ops#71)."""
        doc, _, before = self.edited(consumers.PipeToRemovedPoint)
        message = self.assertFailsNaming(
            doc.getObject("Feature"), "Points", before["pipe_section"][0]
        )
        self.assertNotIn("fatal", message)

    def testPipeNamesItsMissingProfileVertex(self):
        """As for the section, for a pipe that starts at the point (ops#71)."""
        doc, _, before = self.edited(consumers.PipeFromRemovedPoint)
        message = self.assertFailsNaming(doc.getObject("Pipe"), "Points", before["pipe_profile"][0])
        self.assertNotIn("fatal", message)
