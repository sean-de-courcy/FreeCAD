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
default; ops#359). Without the solver (V2) every cut breaks the reference.

The second part, offset copies (ops#358, PLAN decision 86), applies the rule to a survivor that
holds the old name through a GEN section of the same type: a Thickness's or an offset's copy of
the element at another place (`V<V (THK)`)."""

import FreeCAD as App
import Part

from .harness import (
    BROKEN,
    Attached,
    Filleted,
    Guessed,
    Scenario,
    ScenarioError,
    Settled,
    V,
    Warned,
    edge,
    face,
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
    the start cap's edge at x = 2 is gone. It was a `UPP` name from the side face the profile's
    line made, and tier 1 took the edge at the bend, (2, 0, 30), named `UPP` from that face and
    the next leg's, on the top agreement (`PSH;E;UPP`), 30 mm away. The start edge now keeps the
    sketch line's own name and the far end's is its projection (PRJ): the section edge 8 mm up
    and the far twin are only candidates. Nothing stands at the old place: broken."""

    def solid(self, doc, body):
        path = m.sketch(doc, "Path", m.polyline([(0, 0), (0, 30), (20, 30)]), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = "Right corner"  # "Transformed" fails at the right angle (ops#370)

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


# A Part Sweep's ends and corners (ops#375). MakePipeShell reports the edges of the sections at
# the spine's vertices (the start, end and corner wires) as generated from those vertices, so the
# four start edges of a square were `<spine vertex>;SWP;<n>;E;GEN`, told apart only by the
# counter n in the wire's order. A chamfer drawn at the profile's corner between its first and
# second lines shifted the counters, and every start, corner and end edge after it moved silently
# to its neighbour. The start edges now keep the profile's names, the end ones are their
# projections (PRJ), and the corner edges are named from the side faces either side (UPP).


class SweepL(Scenario):
    """A Part Sweep (Part workbench, no body) of the square -2..2 along an L path in XZ (up 30,
    then +X 20, Transition "Right corner"), sketches attached NormalToEdge to edges at the
    start, at the corner and at the end."""

    abstract = True
    area = "SweepEnds"
    path = [(0, 0), (0, 30), (20, 30)]
    solid = True
    profileZ = 0

    def build(self, doc):
        path = m.sketch(doc, "Path", m.polyline(self.path), placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), z=self.profileZ)
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [profile]
        sweep.Spine = (path, [])
        sweep.Solid = self.solid
        sweep.Transition = "Right corner"
        doc.recompute()
        self.consumers(doc, sweep)

    def attach(self, doc, sweep, ref, predicate):
        sketch = doc.addObject("Sketcher::SketchObject", "On" + ref)
        sketch.AttachmentSupport = [(sweep, self.names(sweep, predicate())[0])]
        sketch.MapMode = "NormalToEdge"
        self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())


def startEdgeX2():
    return edge("line", direction=(0, 1, 0), through=(2, 0, 0))


def startEdgeY2():
    return edge("line", direction=(1, 0, 0), through=(0, 2, 0))


def cornerEdgeX2():
    return edge("line", direction=(0, 1, 0), through=(2, 0, 28))


def endEdgeTop():
    return edge("line", direction=(0, 1, 0), through=(20, 0, 32))


class SweepProfileChamfered(SweepL):
    """The edit chamfers the profile's corner (2, -2), between its first line (y = -2) and its
    second (x = 2), as a new fifth line. Every referenced edge survives, the x = 2 ones shortened
    by 1 mm."""

    REFS = ("start_x2", "start_y2", "corner_x2", "end_top")

    def consumers(self, doc, sweep):
        self.attach(doc, sweep, "start_x2", startEdgeX2)
        self.attach(doc, sweep, "start_y2", startEdgeY2)
        self.attach(doc, sweep, "corner_x2", cornerEdgeX2)
        self.attach(doc, sweep, "end_top", endEdgeTop)

    def edit(self, doc):
        m.setLines(doc.Profile, {0: ((-2, -2), (1, -2)), 1: ((2, -1), (2, 2))})
        doc.Profile.addGeometry(Part.LineSegment(V(1, -2, 0), V(2, -1, 0)), False)


class SweepTowardsProfileChamfered(SweepProfileChamfered):
    """The spine drawn towards the profile, from (20, 30) to (0, 0): the shell starts at x = 20
    and ends at the profile, whose names stay at z = 0."""

    path = [(20, 30), (0, 30), (0, 0)]


class SweepStartCapEdgeCutAway(SweepL):
    """ops#375's check: ops#351's PipeStartCapEdgeCutAway as a Part Sweep, a Part::Cut whose tool
    grows from a dimple in the start cap to the slab z 0..8. The start edge at x = 2 is gone, and
    no edge at the corner relates to it: broken (it already was before ops#375)."""

    REFS = ("start_x2",)

    def build(self, doc):
        path = m.sketch(doc, "Path", m.polyline(self.path), placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2))
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [profile]
        sweep.Spine = (path, [])
        sweep.Solid = True
        sweep.Transition = "Right corner"
        tool = doc.addObject("Part::Box", "Tool")
        tool.Length, tool.Width, tool.Height = 2, 2, 2
        tool.Placement = App.Placement(V(-1, -1, -1), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = sweep
        cut.Tool = tool
        doc.recompute()
        self.attach(doc, cut, "start_x2", self.expectEdge)

    def edit(self, doc):
        tool = doc.Tool
        tool.Length, tool.Width, tool.Height = 10, 10, 9
        tool.Placement = App.Placement(V(-5, -5, -1), App.Rotation())

    def expectEdge(self):
        return startEdgeX2() if self.stepName is None else BROKEN


# Fork PR 352 round 1. A lateral edge (a profile vertex swept along one leg of the spine) was told
# apart from the other legs' by a counter, and leg 0's took the start vertex's name as a
# connected name once there were two legs: appending a segment at the far end of a straight spine
# gave leg 1 the name leg 0 had, and deleting an L's last segment gave leg 0 leg 1's. A lateral
# edge is now named after its profile vertex and the spine edge it runs along, as a side face is
# after its profile edge and spine edge.


class SweepStraight(SweepL):
    """A Part Sweep of the square -2..2 along a straight path up Z (0..30), the Sweep's sketches
    attached NormalToEdge."""

    abstract = True
    path = [(0, 0), (0, 30)]


def lateralEdgeLeg0():
    """The edge the profile's corner (2, 2) sweeps along the first leg, up Z."""
    return edge("line", direction=(0, 0, 1), through=(2, 2, 0))


def lateralEdgeLeg1():
    """The edge the profile's corner (2, 2) sweeps along the L's second leg, along X at z = 28."""
    return edge("line", direction=(1, 0, 0), through=(0, 2, 28))


class SweepSegmentAppended(SweepStraight):
    """The edit appends a segment along +X at the path's far end (Right corner): the lateral
    edge on the first leg survives, shortened."""

    REFS = ("lateral_leg0", "start_x2")

    def consumers(self, doc, sweep):
        self.attach(doc, sweep, "lateral_leg0", lateralEdgeLeg0)
        self.attach(doc, sweep, "start_x2", startEdgeX2)

    def edit(self, doc):
        doc.Path.addGeometry(Part.LineSegment(V(0, 30, 0), V(20, 30, 0)), False)


class SweepShellSegmentAppended(SweepSegmentAppended):
    """As SweepSegmentAppended, the Sweep a shell (Solid off)."""

    solid = False


class SweepLastSegmentDeleted(SweepL):
    """The edit deletes the L's second leg: the lateral edge on the first leg survives, the one
    on the second is gone (broken; before PR 352 it broke too, and round 0 moved it silently to
    the first leg's)."""

    REFS = ("lateral_leg0", "lateral_leg1")

    def consumers(self, doc, sweep):
        self.attach(doc, sweep, "lateral_leg0", lateralEdgeLeg0)
        self.attach(doc, sweep, "lateral_leg1", self.expectLeg1)

    def edit(self, doc):
        doc.Path.delGeometry(1)

    def expectLeg1(self):
        return lateralEdgeLeg1() if self.stepName is None else BROKEN


# A profile inside the spine (fork PR 352 round 1, review 2). The ends take the profile's names
# only when it lies at an end of the spine; otherwise they keep the names the spine's end vertices
# give them, whatever the profile's place. In round 0 the profile's names went to the end nearer
# it, so moving the profile across the spine's middle swapped the ends' names silently.


def endEdgeYm(z):
    """The end edge on y = -2 (along X) at height z."""
    return edge("line", direction=(1, 0, 0), through=(0, -2, z))


class SweepProfileCrossesMiddle(SweepStraight):
    """The square sits at z = 14 on the path 0..30; the edit moves it to z = 16. The edges on
    y = -2 at both ends stay where they are."""

    REFS = ("start_ym", "end_ym")
    profileZ = 14

    def consumers(self, doc, sweep):
        self.attach(doc, sweep, "start_ym", lambda: endEdgeYm(0))
        self.attach(doc, sweep, "end_ym", lambda: endEdgeYm(30))

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())


# A Sweep to or from a point (a Part::Vertex section; fork PR 352 round 1, review 1). With Solid
# on, round 0 crashed: the solid was made before the ends were read, and a point section's ends
# were then null.


class SweepPoint(SweepStraight):
    """A Part Sweep along the straight path up Z (0..30) between the square -2..2 and a point on
    the path (`point`, a Part::Vertex), in `order`. A sketch attached by Translate to the apex
    (the point's vertex), one NormalToEdge on the square's edge at x = 2. The edit grows the
    square to -3..3: the apex stays, the edge moves to x = 3."""

    abstract = True
    REFS = ("apex", "square_x")
    pointFirst = False

    def build(self, doc):
        path = m.sketch(doc, "Path", m.polyline(self.path), placement=XZ)
        squareZ, pointZ = (30, 0) if self.pointFirst else (0, 30)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), z=squareZ)
        point = doc.addObject("Part::Vertex", "Point")
        point.Z = pointZ
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [point, profile] if self.pointFirst else [profile, point]
        sweep.Spine = (path, [])
        sweep.Solid = self.solid
        doc.recompute()
        if not sweep.isValid() or sweep.Shape.isNull():
            raise ScenarioError("the sweep failed: " + str(sweep.State))
        self.squareZ, self.pointZ = squareZ, pointZ
        apex = sketchOnVertex(doc, sweep, vertex((0, 0, pointZ)), "OnApex")
        self.ref("apex", apex, "AttachmentSupport", lambda: vertex((0, 0, self.pointZ)), Attached())
        self.attach(doc, sweep, "square_x", self.expectSquareEdge)

    def edit(self, doc):
        m.setLines(
            doc.Profile,
            {
                0: ((-3, -3), (3, -3)),
                1: ((3, -3), (3, 3)),
                2: ((3, 3), (-3, 3)),
                3: ((-3, 3), (-3, -3)),
            },
        )

    def expectSquareEdge(self):
        # The sweep's edges are B-splines: found by a point of the edge
        x = 2 if self.stepName is None else 3
        return edge(contains=(x, 0, self.squareZ))


def sketchOnVertex(doc, obj, predicate, name):
    sketch = doc.addObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = [(obj, Scenario.names(obj, predicate)[0])]
    sketch.MapMode = "Translate"
    return sketch


class SweepSquareToPoint(SweepPoint):
    solid = True


class SweepSquareToPointShell(SweepPoint):
    solid = False


class SweepPointToSquare(SweepPoint):
    solid = True
    pointFirst = True


class SweepPointToSquareShell(SweepPoint):
    solid = False
    pointFirst = True


# A profile away from the spine's ends (fork PR 352 round 2). Round 1 named the end wires there
# from the spine's end vertices alone, told apart by a counter in the profile's edge order
# (`<spine vertex>;SWP;<n>`), so a chamfer on the profile moved the end references silently. Each
# end edge is now also generated from the profile edge whose side face it bounds, and each end
# vertex from the profile vertex whose lateral edge it ends.


def chamferProfile(sketch):
    """Chamfers the square's corner (2, -2), between its first line (y = -2) and its second
    (x = 2), as a new fifth line."""
    m.setLines(sketch, {0: ((-2, -2), (1, -2)), 1: ((2, -1), (2, 2))})
    sketch.addGeometry(Part.LineSegment(V(1, -2, 0), V(2, -1, 0)), False)


class SweepInteriorProfileChamfered(SweepStraight):
    """The square sits at z = 14 on the path 0..30; the edit chamfers it. The edges on x = 2 and
    y = 2 at both ends stay theirs (the x = 2 ones shortened by 1 mm), and so does the vertex
    (-2, 2) at both ends."""

    REFS = ("start_x2", "start_y2", "start_v", "end_x2", "end_y2", "end_v")
    profileZ = 14
    startZ, endZ = 0, 30

    def consumers(self, doc, sweep):
        self.attach(doc, sweep, "start_x2", lambda: self.edgeX2(self.startZ))
        self.attach(doc, sweep, "start_y2", lambda: self.edgeY2(self.startZ))
        self.attachVertex(doc, sweep, "start_v", lambda: self.startZ)
        self.attach(doc, sweep, "end_x2", lambda: self.edgeX2(self.endZ))
        self.attach(doc, sweep, "end_y2", lambda: self.edgeY2(self.endZ))
        self.attachVertex(doc, sweep, "end_v", lambda: self.endZ)

    def attachVertex(self, doc, sweep, ref, z):
        """z() gives the end's height when the reference is checked (an edit may move it)."""
        predicate = lambda: vertex((-2, 2, z()))
        sketch = sketchOnVertex(doc, sweep, predicate(), "On" + ref)
        self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())

    @staticmethod
    def edgeX2(z):
        return edge("line", direction=(0, 1, 0), through=(2, 0, z))

    @staticmethod
    def edgeY2(z):
        return edge("line", direction=(1, 0, 0), through=(0, 2, z))

    def edit(self, doc):
        for sketch in self.chamfered(doc):
            chamferProfile(sketch)

    def chamfered(self, doc):
        return [doc.Profile]


class SweepShellInteriorProfileChamfered(SweepInteriorProfileChamfered):
    """As SweepInteriorProfileChamfered, the Sweep a shell (Solid off): no cap faces."""

    solid = False


class SweepInteriorProfileChamferedTowards(SweepInteriorProfileChamfered):
    """As SweepInteriorProfileChamfered, the path drawn downwards (30..0): the shell starts at
    z = 30."""

    path = [(0, 30), (0, 0)]


class SweepNearStartProfileChamfered(SweepInteriorProfileChamfered):
    """As SweepInteriorProfileChamfered, the square 3e-4 above the path's start: further than
    MakePipeShell's 3D tolerance (1e-4), so not at the end."""

    profileZ = 3e-4


class SweepInteriorFirstSectionChamfered(SweepInteriorProfileChamfered):
    """Two squares, the first at z = 10 inside the path 0..30, the last at its end (z = 30); the
    edit chamfers both. The ends' edges and vertices stay theirs."""

    def build(self, doc):
        path = m.sketch(doc, "Path", m.polyline(self.path), placement=XZ)
        first = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), z=10)
        last = m.sketch(doc, "Last", m.rectangle(-2, -2, 2, 2), z=30)
        sweep = doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [first, last]
        sweep.Spine = (path, [])
        sweep.Solid = self.solid
        sweep.Transition = "Right corner"
        doc.recompute()
        self.consumers(doc, sweep)

    def chamfered(self, doc):
        return [doc.Profile, doc.Last]


# One rule for both cases (fork PR 352 round 3, ops#425). Round 2 gave the ends the profile's
# names (its own at one end, their projections at the other) only when the profile lay at an end
# of the path, within MakePipeShell's 3D tolerance (1e-4), and named them after the path's end
# vertices otherwise: an edit that took the profile across that band renamed every end element,
# and the references broke. The end that keeps the profile's own names is now the one behind the
# profile's plane, wherever the profile sits on the path.


def reverseLine(sketch, index):
    """Swaps the end points of a line, keeping its geometry ID (through a point between them)."""
    geometry = sketch.Geometry
    start, end = V(geometry[index].StartPoint), V(geometry[index].EndPoint)
    geometry[index].StartPoint = start + (end - start) * 0.75
    geometry[index].EndPoint = start
    geometry[index].StartPoint = end
    sketch.Geometry = geometry


class SweepPathStartMovedOut(SweepInteriorProfileChamfered):
    """The square at the path's start (z = 0); the edit moves the path's start 2e-4 down, so the
    square lies inside the path, beyond the tolerance. The ends' edges and vertices stay theirs,
    the start ones moved down with the path's start."""

    profileZ = 0
    path = [(0, 0), (0, 30)]
    movedStart = -2e-4

    def edit(self, doc):
        m.setLines(doc.Path, {0: ((0, self.movedStart), (0, 30))})
        self.startZ = self.movedStart


class SweepPathStartMovedIn(SweepPathStartMovedOut):
    """As SweepPathStartMovedOut the other way: the path starts 2e-4 below the square, and the
    edit moves its start up to the square's plane."""

    path = [(0, -2e-4), (0, 30)]
    startZ = -2e-4
    movedStart = 0


class SweepPathExtendedBeforeProfile(SweepPathStartMovedOut):
    """As SweepPathStartMovedOut, the path's start moved 5 mm down."""

    movedStart = -5


class SweepPathShortenedToProfile(SweepPathStartMovedOut):
    """The square sits at z = 14 on the path 0..30; the edit moves the path's start up to it."""

    profileZ = 14
    movedStart = 14


class SweepProfileAtEndMovedInside(SweepInteriorProfileChamfered):
    """The square at the path's end (z = 30); the edit moves it inside, to z = 16. The ends stay
    where they are, and so do their edges and vertices."""

    profileZ = 30

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())


class SweepInteriorPathReversed(SweepInteriorProfileChamfered):
    """The square sits at z = 14 on the path 0..30; the edit reverses the path's line, keeping its
    geometry ID. The ends stay where they are, and so do their edges and vertices (round 2 named
    them after the path's end vertices, which the reversal swaps: both ends swapped)."""

    def edit(self, doc):
        reverseLine(doc.Path, 0)


class SweepPathReversed(SweepInteriorPathReversed):
    """As SweepInteriorPathReversed, the square at the path's start (coverage: round 2 held it,
    the profile's names going to the end nearer the profile)."""

    profileZ = 0


# Offset copies (ops#358, PLAN decision 86). A Thickness's or an offset's copy of an element is
# named after it with a GEN section of the same type (`<outer corner>;THK;V;GEN`): a copy at
# another place. Below a GEN section a name is a source, so the copy is geometric evidence like
# the derived survivors above: when the shave removes the referenced element, the place decides
# (a warned policy-D guess to the shave's own element when it stands within the guess width and
# shares the old element's source, else broken, the copy listed first). Before ops#358 a vertex
# or a line edge moved silently to its copy at tier 1 (`notes/solver-offset-gen.md` section 2).

X = (1, 0, 0)
Y = (0, 1, 0)


def rimEdge(x):
    """The top rim edge along Y at x, z = 10."""
    return edge("line", direction=Y, through=(x, 5, 10))


class Hollowed(Scenario):
    """A block 20 x 10 x 10 hollowed by a Thickness (top open, `value`, inward unless `outward`,
    join `join`) and a through-all Pocket from z = 10 notching the x = 0 wall (x -5..0.5,
    y 4..6), with a consumer on an element at x = 20. The edit moves the notch onto `shave`
    (x0, y0, x1, y1), which removes that element; its offset copy survives at a distance.
    Diagonal 24.5 (inward): tier 3's strict distance 0.245 mm, the guess width 1.22 mm."""

    abstract = True
    area = "OffsetCopies"
    value = 2.0
    outward = False
    join = "Arc"
    shave = (19.5, -5, 25, 15)

    def build(self, doc):
        body = m.body(doc)
        block = m.pad(body, m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body), 10)
        doc.recompute()
        thickness = body.newObject("PartDesign::Thickness", "Thickness")
        top = face("plane", normal=(0, 0, 1), through=(0, 0, 10))
        thickness.Base = (block, self.names(block, top))
        thickness.Value = self.value
        thickness.Reversed = not self.outward
        thickness.Join = self.join
        doc.recompute()
        notch = m.sketch(doc, "Shave", m.rectangle(-5, 4, 0.5, 6), body, z=10)
        pocket = m.pocketThroughAll(body, notch)
        doc.recompute()
        self.consumer(doc, body, pocket)

    def edit(self, doc):
        m.moveRectangle(doc.Shave, *self.shave)


class OnTopCorner:
    """A sketch attached (Translate) to the top corner (20, 0, 10)."""

    REFS = ("sketch_corner",)

    def consumer(self, doc, body, pocket):
        sketch = body.newObject("Sketcher::SketchObject", "OnCorner")
        sketch.AttachmentSupport = [(pocket, self.names(pocket, vertex((20, 0, 10)))[0])]
        sketch.MapMode = "Translate"
        self.ref("sketch_corner", sketch, "AttachmentSupport", self.expectCorner, Attached())

    def expectCorner(self):
        return vertex((20, 0, 10)) if self.stepName is None else self.cornerAfter()


class OnRimEdge:
    """A fillet (0.5) on the top rim edge along Y at x = 20."""

    REFS = ("fillet_rim",)

    def consumer(self, doc, body, pocket):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, rimEdge(20)))
        fillet.Radius = 0.5
        self.ref("fillet_rim", fillet, "Base", self.expectRim, Filleted(0.5))

    def expectRim(self):
        return rimEdge(20) if self.stepName is None else self.rimAfter()


class OnWall:
    """A sketch attached (FlatFace) to the wall x = 20 (normal `wallNormal`)."""

    REFS = ("sketch_wall",)
    wallNormal = X

    def consumer(self, doc, body, pocket):
        sketch = body.newObject("Sketcher::SketchObject", "OnWall")
        wall = face("plane", normal=self.wallNormal, through=(20, 5, 5))
        sketch.AttachmentSupport = [(pocket, self.names(pocket, wall)[0])]
        sketch.MapMode = "FlatFace"
        self.ref("sketch_wall", sketch, "AttachmentSupport", self.expectWall, Attached())

    def expectWall(self):
        if self.stepName is None:
            return face("plane", normal=self.wallNormal, through=(20, 5, 5))
        return BROKEN


class ThicknessCornerShaved(OnTopCorner, Hollowed):
    """ops#358's repro: inward 2, the shave from x = 19.5 removes the outer wall and its top
    corner. The inner corner (18, 2, 10), `<corner>;THK;V;GEN`, survives 2.83 mm away; the
    shave's own corner (19.5, 0, 10) stands 0.5 mm away and shares the profile sketch and the
    pad: policy D's warned guess to it (decision 86 Q2). Before: tier 1, silent, to the inner
    corner."""

    def cornerAfter(self):
        return Guessed(vertex((19.5, 0, 10))) if self.solver else BROKEN


class ThicknessCornerShavedAncestry(AncestryRule, ThicknessCornerShaved):
    """The repro under NamingSolver/Tier1Derived = ancestry (the rule before ops#335 and
    ops#358): the sketch moves to the inner corner, silently (wrong by geometry; the comparison
    setting's expected result)."""

    def cornerAfter(self):
        return Settled(vertex((18, 2, 10))) if self.solver else BROKEN


class ThicknessCornerShavedWide(OnTopCorner, Hollowed):
    """The shave from x = 18.5: its corner (18.5, 0, 10) is 1.5 mm away, the inner corner 2.83:
    nothing within the guess width (1.22 mm). Broken, the inner corner listed first."""

    shave = (18.5, -5, 25, 15)

    def cornerAfter(self):
        return BROKEN


class ThicknessCornerShavedHalf(OnTopCorner, Hollowed):
    """A 0.5 mm wall: the inner corner (19.5, 0.5, 10) is 0.71 mm away and the shave's corner
    (19.5, 0, 10) 0.5 mm, both within the guess width and within the gap factor of each other:
    ambiguous, broken."""

    value = 0.5

    def cornerAfter(self):
        return BROKEN


class ThicknessRimEdgeShaved(OnRimEdge, Hollowed):
    """Inward 2: the rim edge x = 20 goes with the wall; the inner rim edge x = 18,
    `<rim edge>;THK;E;GEN`, survives 2 mm away, parallel (tier 2 can't tell lines apart by
    direction). The shave's edge x = 19.5 stands 0.5 mm away, but it is named from the top ring
    and the pocket, without the rim edge's source (the profile's line g2): policy D doesn't guess
    it, and the reference breaks, the inner rim edge listed first. Before: tier 1, silent, to the
    inner rim edge."""

    def rimAfter(self):
        return BROKEN


class ThicknessRimEdgeShavedAncestry(AncestryRule, ThicknessRimEdgeShaved):
    """The rim edge under the rule before ops#358: the fillet moves to the inner rim edge,
    silently (the comparison setting's expected result)."""

    def rimAfter(self):
        return Settled(rimEdge(18)) if self.solver else BROKEN


class ThicknessVerticalEdgeShaved(Hollowed):
    """The vertical edge (20, 0, z): its inner copy (18, 2, z) is named through the two inner
    walls (E<F<F<E, ops#335's derived path), so the place decided before ops#358 too: a warned
    guess to the shave's edge (19.5, 0, z), 0.5 mm away. Unchanged by ops#358."""

    REFS = ("fillet_edge",)

    @staticmethod
    def vertical(x):
        return edge("line", direction=(0, 0, 1), through=(x, 0, 5))

    def consumer(self, doc, body, pocket):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.vertical(20)))
        fillet.Radius = 0.5
        self.ref("fillet_edge", fillet, "Base", self.expectEdge, Filleted(0.5))

    def expectEdge(self):
        if self.stepName is None:
            return self.vertical(20)
        return Guessed(self.vertical(19.5)) if self.solver else BROKEN


class ThicknessWallShaved(OnWall, Hollowed):
    """The wall x = 20: its inner copy x = 18 is `F<F` with the opposite normal; tier 2 rejects
    it (broken before ops#358 too, now with the copy listed as derived)."""


class ThicknessOutwardCornerShaved(OnTopCorner, Hollowed):
    """Outward 2, Join=Intersection (every outer element a same-type GEN of the block's): the
    cavity's corner (20, 0, 10) is the source. A slot x 19.5..21 removes the cavity wall x = 20
    and keeps the skin x 21..22, whose corner (22, -2, 10) is the copy, 2.83 mm away. The slot's
    corner (19.5, 0, 10) on the wall y = 0 stands 0.5 mm away: a warned guess to it. Before:
    tier 1, silent, to the skin's corner."""

    outward = True
    join = "Intersection"
    shave = (19.5, -5, 21, 15)

    def cornerAfter(self):
        return Guessed(vertex((19.5, 0, 10))) if self.solver else BROKEN


class ThicknessOutwardCornerShavedAncestry(AncestryRule, ThicknessOutwardCornerShaved):
    """The outward corner under the rule before ops#358: the sketch moves to the skin's corner,
    silently (the comparison setting's expected result)."""

    def cornerAfter(self):
        return Settled(vertex((22, -2, 10))) if self.solver else BROKEN


class ThicknessOutwardRimEdgeShaved(OnRimEdge, Hollowed):
    """Outward 2, Join=Intersection, the cavity's rim edge x = 20: the slot removes it; the
    skin's rim edge x = 22 is the copy, 2 mm away, and the slot's rim edge x = 21 stands 1 mm
    away without the old edge's source: broken, the copy listed first. Before: tier 1, silent,
    to the skin's rim edge."""

    outward = True
    join = "Intersection"
    shave = (19.5, -5, 21, 15)

    def rimAfter(self):
        return BROKEN


class ThicknessOutwardWallShaved(OnWall, Hollowed):
    """Outward 2, Join=Intersection, the cavity wall x = 20 (normal -X): the skin's face x = 22
    (normal +X) is `F<F` at 2 mm with the opposite normal: broken, as before ops#358."""

    outward = True
    join = "Intersection"
    shave = (19.5, -5, 21, 15)
    wallNormal = (-1, 0, 0)


class Offset2DFrame(Scenario):
    """Part workbench: a sketch rectangle 0..20 x 0..10 offset inward by 1 with Fill (a frame
    face, Part::Offset2D), and a Part::Cut with a tool box notching the x = 0 side; the edit
    moves the tool onto x 19.5..25. A consumer on the outer side x = 20 (`g2`), which the tool
    removes; its copy at x = 19, `g2;OFF;E;GEN`, survives 1 mm away. Diagonal 22.4: the guess
    width 1.12 mm."""

    abstract = True
    area = "OffsetCopies"

    def build(self, doc):
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10))
        offset = doc.addObject("Part::Offset2D", "Offset2D")
        offset.Source = profile
        offset.Value = -1
        offset.Fill = True
        tool = doc.addObject("Part::Box", "Tool")
        tool.Length, tool.Width, tool.Height = 5.5, 2, 4
        tool.Placement = App.Placement(V(-5, 4, -2), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = offset
        cut.Tool = tool
        doc.recompute()
        self.consumer(doc, cut)

    def edit(self, doc):
        tool = doc.Tool
        tool.Length, tool.Width, tool.Height = 5.5, 20, 4
        tool.Placement = App.Placement(V(19.5, -5, -2), App.Rotation())


class Offset2DFrameEdge(Offset2DFrame):
    """A sketch attached (NormalToEdge) to the outer edge x = 20. The cut's edge x = 19.5 is
    0.5 mm away and the copy x = 19 1 mm, both within the guess width and the gap factor:
    ambiguous, broken (before ops#358 as well, with the copy as tier 1's)."""

    REFS = ("sketch_edge",)

    @staticmethod
    def side():
        return edge("line", direction=Y, through=(20, 5, 0))

    def consumer(self, doc, cut):
        sketch = doc.addObject("Sketcher::SketchObject", "OnEdge")
        sketch.AttachmentSupport = [(cut, self.names(cut, self.side())[0])]
        sketch.MapMode = "NormalToEdge"
        self.ref("sketch_edge", sketch, "AttachmentSupport", self.expectEdge, Attached())

    def expectEdge(self):
        return self.side() if self.stepName is None else BROKEN


class Offset2DFrameCorner(Offset2DFrame):
    """A sketch attached (Translate) to the outer corner (20, 0, 0). The inner corner (19, 1, 0)
    is named from the two offset edges (V<E<V, derived since ops#335), 1.41 mm away; the cut's
    corner (19.5, 0, 0) 0.5 mm: a warned guess to it, unchanged by ops#358."""

    REFS = ("sketch_corner",)

    def consumer(self, doc, cut):
        sketch = doc.addObject("Sketcher::SketchObject", "OnCorner")
        sketch.AttachmentSupport = [(cut, self.names(cut, vertex((20, 0, 0)))[0])]
        sketch.MapMode = "Translate"
        self.ref("sketch_corner", sketch, "AttachmentSupport", self.expectCorner, Attached())

    def expectCorner(self):
        if self.stepName is None:
            return vertex((20, 0, 0))
        return Guessed(vertex((19.5, 0, 0))) if self.solver else BROKEN


class PartOffsetCavityCorner(Scenario):
    """Part workbench: a Box 20 x 10 x 10 and its Part::Offset by 2 (Join=Intersection; every
    element a same-type GEN of the box's), the box cut out of it (Part::Cut: a closed hollow), and
    a second Part::Cut with a slot box. The edit moves the slot onto x 19.5..21, which removes the
    cavity's corner (20, 0, 10); the slot's corner (19.5, 0, 10) stands 0.5 mm away: a warned
    guess to it. The cut names the cavity from the box, so the offset's corner
    (`<box corner>;OFS;V;GEN`, 3.46 mm away) never held the cavity corner's name, and the guess
    was the same before ops#358: a Part::Offset alone holds only the copy, and with Fill it is
    invalid in this build (`notes/solver-offset-gen.md` section 2), so Part::Offset meets the
    rule only through models like this one."""

    area = "OffsetCopies"
    REFS = ("sketch_corner",)

    def build(self, doc):
        box = doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 20, 10, 10
        offset = doc.addObject("Part::Offset", "Offset")
        offset.Source = box
        offset.Value = 2
        offset.Join = "Intersection"
        hollow = doc.addObject("Part::Cut", "Hollow")
        hollow.Base = offset
        hollow.Tool = box
        slot = doc.addObject("Part::Box", "Slot")
        slot.Length, slot.Width, slot.Height = 1.5, 2, 20
        slot.Placement = App.Placement(V(-1, 4, -5), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base = hollow
        cut.Tool = slot
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnCorner")
        sketch.AttachmentSupport = [(cut, self.names(cut, vertex((20, 0, 10)))[0])]
        sketch.MapMode = "Translate"
        self.ref("sketch_corner", sketch, "AttachmentSupport", self.expectCorner, Attached())

    def edit(self, doc):
        slot = doc.Slot
        slot.Length, slot.Width = 1.5, 20
        slot.Placement = App.Placement(V(19.5, -5, -5), App.Rotation())

    def expectCorner(self):
        if self.stepName is None:
            return vertex((20, 0, 10))
        return Guessed(vertex((19.5, 0, 10))) if self.solver else BROKEN
