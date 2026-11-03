# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2gs (the rebase of round 2f onto integration + PR 405 + PR 411): review
pr390-r2gs's probes of the conflict resolution in ElementSolver.cpp's tier 3 pick,
`!lacks && !redrawn && (twinClause || nearest.index < 0) && lostOldSource(pick)`, with
`twinClause = state.twinSurvivor >= 0 || saved->twinCount >= 2`: a record that saved two twins or
more, no twin survivor, and a pick at the saved place that D2 calls Quiet or Normal (a redraw:
its unshared sources new) but that is not the old element.

Model of review390r2fp.py: a Pad (Refine off) from an unattached sketch (rectangle x -3..3,
y -0.5..0.5) up to a Part::Feature shell at z = 10 (SIZE 30 at scale 1): the plate x -10..20,
y -10..10 with a rectangular hole x -1..1, y -2..2 and its fill (B-spline faces), so the Pad's
far edge y 0.5 comes in pieces L (x -3..-1), M (the fill) and R (1..3). Pocket circles r 0.3 at
z 10 cross L's far edge twice, at cx -+ D (D = sqrt(0.05)). References `first` (the left crossing)
and `second` (the right one) are the pocket's vertexes there; `*Edges` cases hold the pocket
wall's vertical edges at them.

The expected element is the crossing the reference held, where it lies after the edit; an
ambiguous one may also break (OwnOrBroken); a crossing of a circle that is gone breaks.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Reopens,
    Scenario,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
D = 0.05**0.5


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2gs"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    AFTER = {}
    OWN = False
    EDGES = False
    HOLES = ((-1, -2, 1, 2),)
    RECT = (-3, -0.5, 3, 0.5)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
        if self.EDGES:
            return edge(contains=self.P(x, y, HEIGHT - 1))
        return vertex(self.P(x, y))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self):
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        wires = [outer]
        fills = []
        for hx0, hy0, hx1, hy1 in self.HOLES:
            wires.append(self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)]))
            fills.append(
                Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]))
                .toNurbs()
                .Faces[0]
            )
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), wires).toNurbs().Faces[0]
        return Part.Shell([plate] + fills)

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        plate = m.feature(doc, "Plate", self.shell())
        profile = m.sketch(doc, "Profile", m.rectangle(*[self.S(v) for v in self.RECT]), body)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % (i + 1) for i in range(len(plate.Shape.Faces))])
        pad.Refine = False
        doc.recompute()
        hole = m.sketch(
            doc,
            "Circles",
            [m.circle(self.S(x), self.S(y), self.S(0.3)) for x, y in self.CIRCLES],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(pocket, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(pocket, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            found = self.place(*self.AFTER[name])
            return OwnOrBroken(found) if self.OWN else found

        return expect

    # Objects are fetched by name so that a reopen step may come first
    def hole(self):
        return self.doc.getObject("Circles")

    def redrawCircle(self, index, x, y):
        hole = self.hole()
        hole.delGeometry(index)
        hole.addGeometry(m.circle(self.S(x), self.S(y), self.S(0.3)), False)

    def moveCircle(self, index, x, y):
        hole = self.hole()
        geometry = hole.Geometry
        geometry[index].Center = V(self.S(x), self.S(y), 0)
        hole.Geometry = geometry

    def edit(self, doc):
        self.change(doc)
        self.edited = True


def at(cx):
    """The crossings of a circle centred at cx on L's far edge."""
    return {"first": (cx - D, 0.5), "second": (cx + D, 0.5)}


SPACING = 2 * D  # the crossings' spacing: a redraw this far left puts the right crossing at
# the left one's old place


class R2gsbRedrawShiftSpacing(Base):
    """The circle deleted and drawn again 2D = 0.447 to the LEFT (a new geometry ID): its new
    right crossing (-2.2236) lies exactly where the old left one (`first`) was, a twin of the
    group at the saved place, D2 Quiet (all its unshared sources new). The record saved two twins
    (offset -D from their centroid); the pick has offset +D: out of the saved order. `first` is
    the new left crossing (-2.671) or breaks, never the right one; `second` the new right
    crossing (the one at -2.2236) or breaks. Silent wrong if `first` holds the crossing at the
    old place. (The previous round broke it by the source test; the resolution leaves the
    source test to a non-redraw, the order test must break it.)"""

    OWN = True
    AFTER = at(-2 - SPACING)

    def change(self, doc):
        self.redrawCircle(0, -2 - SPACING, 0.7)


class R2gsbRedrawShiftSpacingEdges(R2gsbRedrawShiftSpacing):
    """As R2gsbRedrawShiftSpacing, the references the pocket wall's vertical edges at the
    crossings."""

    EDGES = True


class R2gsbRedrawShiftSpacingRight(Base):
    """The circle deleted and drawn again 2D to the RIGHT: the new left crossing (-1.7764) lies
    where `second` was. `second` is the new right crossing (-1.329) or breaks, never the left
    one; `first` the new left crossing or breaks."""

    OWN = True
    AFTER = at(-2 + SPACING)

    def change(self, doc):
        self.redrawCircle(0, -2 + SPACING, 0.7)


class R2gsbRedrawShiftHalf(Base):
    """The circle deleted and drawn again D = 0.2236 to the left: the old left place lies midway
    between the new crossings (-2.447 and -2.0): a tie for tier 3's nearest."""

    OWN = True
    AFTER = at(-2 - D)

    def change(self, doc):
        self.redrawCircle(0, -2 - D, 0.7)


class R2gsbRedrawShiftQuarter(Base):
    """The circle deleted and drawn again D/2 to the left: the new left crossing (-2.335) is
    0.11 from the old left place, the new right (-1.888) 0.11 from the old right place."""

    OWN = True
    AFTER = at(-2 - D / 2)

    def change(self, doc):
        self.redrawCircle(0, -2 - D / 2, 0.7)


class R2gsbRedrawLeavesEnd(Base):
    """The circle deleted and drawn again at (-2.8, 0.7): its crossings -3.0236 (beyond L's end
    at x -3: gone) and -2.5764 (0.8 from `second`'s old place). The group has one member now:
    `first`'s crossing is gone (break); `second` is the lone crossing (own or break)."""

    OWN = True
    AFTER = {"first": None, "second": (-2.8 + D, 0.5)}

    def change(self, doc):
        self.redrawCircle(0, -2.8, 0.7)


class R2gsbMovedAwayNewCircleAtPlace(Base):
    """Circle A is moved away (to (0, 5): off the pad, its geometry ID kept) and a NEW circle C
    (a new ID) is drawn at A's old centre and radius in the same edit. The record saved two twins;
    A's crossings are gone, and C's crossings sit exactly at A's old places, sources new (D2
    Quiet). A (the circle the reference belongs to) still exists elsewhere: the references to its
    crossings break, but D2 can't tell C from A drawn again. Expected BROKEN: wrong on both builds
    would be debt."""

    AFTER = {"first": None, "second": None}

    def change(self, doc):
        self.moveCircle(0, 0, 5)
        hole = self.hole()
        hole.addGeometry(m.circle(self.S(-2), self.S(0.7), self.S(0.3)), False)


class R2gsbRedrawShiftSpacingReopen(Reopens, R2gsbRedrawShiftSpacing):
    """As R2gsbRedrawShiftSpacing, the file saved, closed and opened before the edit."""

    steps = ("reopen", "edit")


class R2gsbRedrawShiftSpacingThenReopen(Reopens, R2gsbRedrawShiftSpacing):
    """As R2gsbRedrawShiftSpacing, the file saved, closed and opened after the edit (the break or
    the pick must be what the first recompute made)."""

    steps = ("edit", "reopen")


class R2gsbTwoStepsRedrawThenBack(Base):
    """Composed edits: the circle redrawn 2D to the left (the right crossing at the left one's
    old place), then redrawn back at (-2, 0.7). After the second step the crossings are where
    they were (new IDs again): the right answer after the second step is the original crossing
    or a break; the first step's pick must not have stored the twin at the old place."""

    steps = ("left", "back")
    OWN = True

    def expectation(self, name):
        def expect():
            step = getattr(self, "stepName", None)
            if step == "left":
                found = self.place(*at(-2 - SPACING)[name])
            elif step == "back":
                found = self.place(*self.BEFORE[name])
            else:
                return self.place(*self.BEFORE[name])
            return OwnOrBroken(found)

        return expect

    def left(self, doc):
        self.redrawCircle(0, -2 - SPACING, 0.7)

    def back(self, doc):
        self.redrawCircle(0, -2, 0.7)

    def edit(self, doc):
        pass


class R2gsbNewSketchProfile(Base):
    """The Pocket's Profile retargeted to a NEW sketch object holding the same circle at the
    same place (D2 Normal: its source is another object's). Policy D: a guess needs a surviving
    source; the new sketch is none: both references break."""

    AFTER = {"first": None, "second": None}

    def change(self, doc):
        body = doc.getObject("Body")
        sketch = m.sketch(
            doc,
            "Circles2",
            [m.circle(self.S(-2), self.S(0.7), self.S(0.3))],
            body,
            z=self.S(HEIGHT),
        )
        doc.getObject("Pocket").Profile = sketch
        doc.getObject("Circles").Visibility = False


class R2gsbSiblingNewIdSameSketch(Base):
    """Circles A (-2, 0.7) and B (2, 0.7) in one sketch. A deleted; B deleted and drawn again
    (a new ID) at (-1.97, 0.7): its crossings lie 0.03 from A's old ones, an order group of the
    saved size at the saved offsets, D2 Quiet (all its sources new). A is gone: both break. (A
    new-ID sibling is not the pre-existing one of R2fPSiblingIntoVacated: its sources are new,
    not WasThere.)"""

    CIRCLES = ((-2, 0.7), (2, 0.7))
    AFTER = {"first": None, "second": None}

    def change(self, doc):
        hole = self.hole()
        hole.delGeometry(0)
        hole.delGeometry(0)
        hole.addGeometry(m.circle(self.S(-1.97), self.S(0.7), self.S(0.3)), False)
