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

"""Corpus cases (ops#504, class E; ops#306, row 157): a reorder after an insert at the bar.

Ports `SolverOffReorder|base_link|V2` (`corpus/predicted/E.json`; the report column V2 is the
solver-off configuration: run the module with `FREECAD_SCENARIO_CONFIGS=V2s,V2`, and the ledger
holds both). The case also gives `SolverOffReorder|base_link|V2s`, which the design predicts
correct (fork PRs 270 and 282).

The model is ops#306's probe (`work/291/cyc/probe_cycle.py`): a 20 x 20 x 10 block, a hole (a
pocket of a circle, radius 2, at (10, 10), 3 deep), and a fillet of the block's front top edge
(y = 0, z = 10, x 0..20; radius 1) with its Base on the hole. With the body rolled back to the hole
a notch (a pocket 14..17 x 14..17, 2 deep) is inserted at the bar, so the chain is block, hole,
notch, fillet. With the solver off the insert leaves the fillet's Base on the hole (decision 48),
an earlier object than its base feature, the notch; with the solver on the Base follows the insert
to the notch. The case reads where the Base is after the insert and does not judge that. The edit
moves the fillet above the block.

The expectation (PLAN decisions 57 and 58, the user's option A): a reorder that changes a feature's
base moves its Base link to the new base. Above the block the fillet's base is the block, and the
front top edge is an edge of the block as well: the fillet holds it, on the block, and its result
is the block with that edge filleted. A reorder the body refuses (the reorder is a loud no-op) leaves
the model as it was; the fillet then stays on the hole."""

from PartDesignTests.Scenarios.harness import (
    Filleted,
    Scenario,
    X,
    edge,
)
from PartDesignTests.Scenarios import models as m


class AtPlace:
    """The predicate's elements of whatever shape the Base is on: none where that shape has no
    such element (a Base left on an object that was moved below its owner has the owner's result
    in its shape, where the edge is filleted), so the reference holds a wrong element and the
    verdict is `wrong`, not a case error."""

    def __init__(self, predicate):
        self.predicate = predicate

    def select(self, shape):
        return self.predicate.select(shape)

    one = select

    def __repr__(self):
        return repr(self.predicate)


class SolverOffReorder(Scenario):
    """The fillet moved above the block (the module's docstring)."""

    area = "solver_off_reorder"
    CLASSES = ("E",)
    AXES = ("M1", "E2", "X3")
    ISSUE = "ops#504"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("base_link",)
    steps = ("reorder",)

    refused = False
    baseOn = None

    def frontTopEdge(self):
        return AtPlace(edge("line", direction=X, through=(0, 0, 10)))

    def target(self):
        """The object the Base must be on: where the insert at the bar left it before the reorder
        (the hole with the solver off, decision 48), the block after it."""
        if self.stepName == "reorder" and not self.refused:
            return "Block"
        return self.baseOn

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        sketch = m.sketch(doc, "BlockSketch", m.rectangle(0, 0, 20, 20), body)
        block = m.pad(body, sketch, 10, "Block")
        hole = m.pocket(
            body, m.sketch(doc, "HoleSketch", [m.circle(10, 10, 2)], body, z=10), 3, "Hole"
        )
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (hole, self.names(hole, self.frontTopEdge()))
        fillet.Radius = 1
        doc.recompute()
        body.rollTo(hole)
        notch = m.sketch(doc, "NotchSketch", m.rectangle(14, 14, 17, 17), body, z=10)
        m.pocket(body, notch, 2, "Notch")
        doc.recompute()
        body.rollToEnd()
        doc.recompute()
        self.block = block
        self.baseOn = fillet.Base[0].Name
        self.ref("base_link", fillet, "Base", self.frontTopEdge, Filleted(1), self.target)

    def reorder(self, doc):
        try:
            self.bodyObject.reorderObject([doc.Fillet], self.block, True)
        except Exception:
            self.refused = True
