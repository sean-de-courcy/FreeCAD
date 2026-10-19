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

"""Derived survivors (ops#335, PLAN decision 81): the old element is cut away, and an element
whose name reaches the old one only through an element of another type survives, e.g. the new
bottom edge on the face the old bottom edge generated (`E<F<E`). That shows the survivor is
related to the old element, not that it is where the old element was: the reference solver
decides by its place (tier 3; policy D's wide guess), and breaks when nothing stands there.

Every model has its bottom (z = 0) recessed by a Pocket from below (Reversed), a rectangle
x 5..15, y 2..8 that keeps the model's outer edges. The edit grows the recess to the whole
bottom, so the slab z 0..`depth` and every bottom edge and corner go. Before ops#335 a lone derived
survivor was taken at tier 1, silently, wherever it was (L2, L4: 8 mm up).

Scenarios named `...Ancestry` run with NamingSolver/Tier1Derived = ancestry, the rule before
ops#335, kept for comparison runs: they assert that the setting still gives the old rule, the
reference moved silently to the derived survivor (wrong by geometry, which is why `place` is the
default; ops#359). Without the solver (V2) every cut breaks the reference."""

import FreeCAD as App

from .harness import (
    BROKEN,
    Attached,
    Filleted,
    Guessed,
    Scenario,
    Settled,
    V,
    Warned,
    edge,
    vertex,
)
from . import models as m

XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
SOLVER_GROUP = "User parameter:BaseApp/Preferences/Mod/Part/NamingSolver"


def bottomEdge(z=0.0):
    """The edge along Y at x = 20 (the profile's line g2 at z = 0), at height z."""
    return edge("line", direction=(0, 1, 0), through=(20, 5, z))


class Recessed(Scenario):
    """A solid on the XY plane (`solid()`), the bottom recess, and a consumer on the bottom edge
    at x = 20 or on the corner (20, 0, 0). The edit cuts the slab z 0..`depth` away."""

    abstract = True
    area = "DerivedSurvivors"
    depth = 8

    def solid(self, doc, body):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        self.solid(doc, body)
        recess = m.sketch(doc, "Recess", m.rectangle(5, 2, 15, 8), body)
        pocket = m.pocket(body, recess, self.depth)
        pocket.Reversed = True
        doc.recompute()
        self.consumer(doc, body, pocket)

    def cut(self, doc):
        m.moveRectangle(doc.Recess, -5, -5, 25, 15)

    def uncut(self, doc):
        m.moveRectangle(doc.Recess, 5, 2, 15, 8)

    edit = cut


class OnEdge:
    """A fillet (radius 1) on the bottom edge at x = 20."""

    REFS = ("fillet_bottom",)

    def consumer(self, doc, body, pocket):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, bottomEdge()))
        fillet.Radius = 1
        self.ref("fillet_bottom", fillet, "Base", self.expectEdge, Filleted(1))


class OnCorner:
    """A sketch attached by Translate to the bottom corner (20, 0, 0)."""

    REFS = ("sketch_corner",)

    def consumer(self, doc, body, pocket):
        sketch = body.newObject("Sketcher::SketchObject", "OnCorner")
        sketch.AttachmentSupport = [(pocket, self.names(pocket, vertex((20, 0, 0)))[0])]
        sketch.MapMode = "Translate"
        self.ref("sketch_corner", sketch, "AttachmentSupport", self.expectCorner, Attached())


class Loft:
    """A ruled Loft from the rectangle 0..20 x 0..10 at z = 0 to `top` at z = 15: straight (the
    same rectangle, planar side faces) or tapered (2..18 x 1..9, B-spline side faces)."""

    top = (0, 0, 20, 10)

    def solid(self, doc, body):
        bottom = m.sketch(doc, "Bottom", m.rectangle(0, 0, 20, 10), body)
        top = m.sketch(doc, "Top", m.rectangle(*self.top), body, z=15)
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = bottom
        loft.Sections = [top]
        loft.Ruled = True


class Pad:
    """A Pad 20 x 10 x 10. Its top edges are the bottom edges' projections (PRJ), so the new
    bottom edge after the cut is never the only survivor: S1, S5 of the design note."""

    def solid(self, doc, body):
        m.pad(body, m.sketch(doc, "Bottom", m.rectangle(0, 0, 20, 10), body), 10)


class AncestryRule:
    """NamingSolver/Tier1Derived = ancestry for the run: the rule before ops#335."""

    def run(self):
        group = App.ParamGet(SOLVER_GROUP)
        had = "Tier1Derived" in group.GetStrings()
        old = group.GetString("Tier1Derived", "")
        group.SetString("Tier1Derived", "ancestry")
        try:
            return super().run()
        finally:
            if had:
                group.SetString("Tier1Derived", old)
            else:
                group.RemString("Tier1Derived")


class LoftEdgeCutAway(OnEdge, Loft, Recessed):
    """L2: a straight loft, the slab 8 mm: the bottom edge is gone; the new bottom edge 8 mm up
    on the face the old edge generated is the only element whose name holds it (E<F<E). Nothing
    stands at the old place: broken, the derived edge listed first."""

    def expectEdge(self):
        return bottomEdge() if self.stepName is None else BROKEN


class LoftEdgeCutAwayAncestry(AncestryRule, LoftEdgeCutAway):
    """L2 under the rule before ops#335: the fillet moves 8 mm up to the derived edge, silently
    (wrong by geometry; the comparison setting's expected result)."""

    def expectEdge(self):
        if self.stepName is None:
            return bottomEdge()
        return Settled(bottomEdge(self.depth)) if self.solver else BROKEN


class LoftCornerCutAway(OnCorner, Loft, Recessed):
    """L4: a tapered loft's corner, the slab 8 mm: the new corner (18.9, 0.53, 8) on the edge the
    old corner generated is the only survivor (V<E<V). A vertex has no intrinsic geometry, so
    only its place tells: broken."""

    top = (2, 1, 18, 9)

    def expectCorner(self):
        return vertex((20, 0, 0)) if self.stepName is None else BROKEN


class LoftCornerCutAwayAncestry(AncestryRule, LoftCornerCutAway):
    """L4 under the rule before ops#335: the sketch moves to the new corner 8 mm up, silently
    (wrong by geometry; the comparison setting's expected result)."""

    def expectCorner(self):
        if self.stepName is None:
            return vertex((20, 0, 0))
        # the tapered loft's edge from (20, 0, 0) to (18, 1, 15), at z = depth
        t = self.depth / 15
        return Settled(vertex((20 - 2 * t, t, self.depth))) if self.solver else BROKEN


class TaperedLoftEdgeCutAway(OnEdge, Loft, Recessed):
    """L1: a tapered loft's edge, the slab 8 mm: the derived edge is a B-spline (the section of
    the ruled B-spline face), the old one a line: broken, by tier 2 as before ops#335."""

    top = (2, 1, 18, 9)

    def expectEdge(self):
        return bottomEdge() if self.stepName is None else BROKEN


class LoftEdgeShaved(OnEdge, Loft, Recessed):
    """L3: a straight loft, the slab 0.1 mm, then the cut undone: the new bottom edge 0.1 mm up
    is within tier 3's strict distance (1 % of the diagonal, 0.27 mm): resolved by geometry,
    warned, with a record (silent before ops#335). Undone, the original edge is back and the
    reference snaps back to it, plainly."""

    depth = 0.1
    steps = ("cut", "uncut")

    def expectEdge(self):
        if self.stepName == "cut":
            return Warned(bottomEdge(0.1)) if self.solver else BROKEN
        if self.stepName == "uncut":
            return Settled(bottomEdge())
        return bottomEdge()


class LoftCornerShaved(OnCorner, Loft, Recessed):
    """L5: a straight loft's corner, the slab 0.1 mm: the new corner (20, 0, 0.1) is within tier
    3's strict distance: resolved by geometry, warned; undone, settled on the original."""

    depth = 0.1
    steps = ("cut", "uncut")

    def expectCorner(self):
        if self.stepName == "cut":
            return Warned(vertex((20, 0, 0.1))) if self.solver else BROKEN
        if self.stepName == "uncut":
            return Settled(vertex((20, 0, 0)))
        return vertex((20, 0, 0))


class LoftEdgeCutShallow(OnEdge, Loft, Recessed):
    """A straight loft, the slab 1 mm: beyond tier 3's strict distance (0.27 mm), within the guess
    rules' wide one (5 % of the diagonal, 1.35 mm), the next edge along Y 14 mm away: a warned
    guess (G2, the derived edge shares the old edge's sketch and maker)."""

    depth = 1

    def expectEdge(self):
        if self.stepName is None:
            return bottomEdge()
        return Guessed(bottomEdge(1)) if self.solver else BROKEN


class PadEdgeCutAway(OnEdge, Pad, Recessed):
    """S1: a pad, the slab 8 mm: the new bottom edge (derived) and the top edge (the old edge's
    projection) survive tier 1, neither at the old place: broken, as before ops#335."""

    def expectEdge(self):
        return bottomEdge() if self.stepName is None else BROKEN


class PadEdgeCutShallow(OnEdge, Pad, Recessed):
    """S5: a pad, the slab 1 mm: G1 picks the new bottom edge among tier 1's survivors (1 mm
    away; the top edge 9 mm): a guess, as before ops#335 (the mixed-set rule: tier 3 chose it)."""

    depth = 1

    def expectEdge(self):
        if self.stepName is None:
            return bottomEdge()
        return Guessed(bottomEdge(1)) if self.solver else BROKEN


class PipeStartCapEdgeCutAway(OnEdge, Recessed):
    """ops#351: a Pipe of the square -2..2 along an L path (up 30, then +X 20), the slab 8 mm:
    the start cap's edge at x = 2 (a `UPP` name from the side face the profile's line made) is
    gone. The edge at the bend, (2, 0, 30), between that side face and the next leg's, is named
    `UPP` from both: tier 1 takes it on the top agreement (`PSH;E;UPP`) and the shared face, 30 mm
    away. Nothing stands at the old place: broken."""

    def solid(self, doc, body):
        path = m.sketch(doc, "Path", m.polyline([(0, 0), (0, 30), (20, 30)]), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])

    def build(self, doc):
        body = m.body(doc)
        self.solid(doc, body)
        recess = m.sketch(doc, "Recess", m.rectangle(-1, -1, 1, 1), body)
        pocket = m.pocket(body, recess, self.depth)
        pocket.Reversed = True
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.startEdge()))
        fillet.Radius = 0.5
        self.ref("fillet_bottom", fillet, "Base", self.expectEdge, Filleted(0.5))

    def cut(self, doc):
        m.moveRectangle(doc.Recess, -5, -5, 5, 5)

    edit = cut

    @staticmethod
    def startEdge():
        return edge("line", direction=(0, 1, 0), through=(2, 0, 0))

    def expectEdge(self):
        return self.startEdge() if self.stepName is None else BROKEN
