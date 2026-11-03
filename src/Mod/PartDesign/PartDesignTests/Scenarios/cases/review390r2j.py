# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2j (ops#468): the contest of a pick the twin clause broke, narrowed to picks
`integration` took (takenOnIntegration()). Here the clause runs with no tier 1 survivor (a twin
record of two, round 2f's literal stop): the PR breaks tier 3's pick by T1''s source test, which
`integration` never ran there (no survivor, a nearest within d_max), so `integration` took it and
the pick must still contest its element.

The model (as review390r2h.py): a Pad (Refine off) from an unattached sketch (rectangle x -3..3,
y -0.5..0.5) up to a Part::Feature shell at z = 10: the plate x -10..20, y -10..10 with a hole
x -1..1, y -2..2 and its fill (B-spline faces), so the Pad's far edge y 0.5 comes in pieces L
(x -3..-1), M (-1..1) and R (1..3). Pocket circles r 0.3 centred at y 0.6 (half chord HH =
sqrt(0.08) on y 0.5), one sketch, one Pocket, length 2:
- A at (-1.82, 0.6): two crossings of L, twins; a_right holds the right one (-1.5372).
- E at (-1.2, 0.6): spans x -1, one crossing on L (-1.4828, b_left, a lone one), one on M.
- B at (2, 0.6): a sibling on R.
One edit: A moved clear of the edge to (-1.82, 1.5) (no crossings now), E deleted, B moved to
(-1.78, 0.6): its right crossing -1.4972 lies 0.040 from a_right's place and 0.014 from b_left's.
Both references' elements are gone (A no longer crosses; E is deleted): both must break. B's
crossing is another circle's for each.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
R = 0.3
CY = 0.6
HH = (R * R - (CY - 0.5) ** 2) ** 0.5


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2j"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("a_right", "b_left")
    CIRCLES = ((-1.82, CY), (-1.2, CY), (2.0, CY))
    BEFORE = {"a_right": (-1.82 + HH, 0.5), "b_left": (-1.2 - HH, 0.5)}
    HOLES = ((-1, -2, 1, 2),)
    ONE_OWNER = True
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
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
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(self.S(-3), self.S(-0.5), self.S(3), self.S(0.5)), body
        )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.profile
        pad.Type = "UpToShape"
        pad.UpToShape = (self.plate, ["Face%d" % (i + 1) for i in range(len(self.plate.Shape.Faces))])
        pad.Refine = False
        doc.recompute()
        self.hole = m.sketch(
            doc,
            "Circles",
            [m.circle(self.S(x), self.S(y), self.S(R)) for x, y in self.CIRCLES],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        subs = [self.names(pocket, self.place(*self.BEFORE[n]))[0] for n in self.REFS]
        if self.ONE_OWNER:
            # One owner holding both: a sketch attached at the first, the second its external
            # vertex (the forced matching runs over both)
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[0])]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subs[1])
            self.ref(self.REFS[0], probe, "AttachmentSupport", self.expectation(self.REFS[0]), Attached())
            self.ref(self.REFS[1], probe, "ExternalGeometry", self.expectation(self.REFS[1]))
        else:
            for name, sub in zip(self.REFS, subs):
                point = body.newObject("PartDesign::Point", "On" + name)
                point.AttachmentSupport = [(pocket, sub)]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def after(self, name):
        return BROKEN

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            return self.after(name)

        return expect

    def moveCircle(self, index, x, y):
        geometry = self.hole.Geometry
        geometry[index].Center = V(self.S(x), self.S(y), 0)
        self.hole.Geometry = geometry

    def change(self, doc):
        self.moveCircle(0, -1.82, 1.5)  # A clear of the edge
        self.moveCircle(2, -1.78, CY)  # B next to A's old right crossing
        self.hole.delGeometry(1)  # E

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class R2jNoSurvivorContestOneOwner(Base):
    """a_right and b_left in one owner. a_right (twin record of two, no survivor: A crosses no
    more) takes tier 3's nearest, B's right crossing, on integration (no source test without a
    survivor), and b_left's nearest is the same crossing: they contest it, both broken. On the PR
    a_right breaks by the twin clause's source test; its pick must still contest the crossing
    (takenOnIntegration() true), or b_left takes B's crossing alone: wrong."""


class R2jNoSurvivorContestTwoOwners(Base):
    """The control: each reference in its own datum point, no contest on either build."""

    ONE_OWNER = False


class R2jNoSurvivorContestSwapped(Base):
    """As the one-owner case with the owner's roles swapped (b_left attached, a_right external):
    the entries' order in the owner must not decide the contest."""

    REFS = ("b_left", "a_right")


class R2jLoneLeftOneOwner(Base):
    """A moved to (-2.9, 0.6) instead of clear: its left crossing leaves the Pad's end (x -3), its
    right one stays on L at -2.6172, moved by -1.08 (its twin count 2 -> 1). B and E as above.
    a_right follows A's right crossing or breaks; b_left (its circle gone) must break.
    Integration keeps a_right's name (rank 0, unchanged) and resolves it; the PR renames the
    crossing (`0of2`, ORD, now alone), so a_right goes to the missing solve: tier 1's survivors
    drop by T1', no survivor is left, the twin record of two runs the clause, and tier 3's nearest,
    B's right crossing (0.040 away), breaks by T1''s source test. takenOnIntegration() (integration's
    rule on the PR's state) takes it, so it contests the crossing, and b_left, whose nearest it is,
    stays ambiguous. On integration b_left holds B's crossing alone."""

    def after(self, name):
        if name == "a_right":
            return OwnOrBroken(self.place(-2.9 + HH, 0.5))
        return BROKEN

    def change(self, doc):
        self.moveCircle(0, -2.9, CY)
        self.moveCircle(2, -1.78, CY)
        self.hole.delGeometry(1)


class R2jLoneLeftTwoOwners(R2jLoneLeftOneOwner):
    """The control of R2jLoneLeftOneOwner: one datum point each, no contest."""

    ONE_OWNER = False


class R2jForcedOntoTwinOneOwner(Base):
    """Aimed at the contest's state (takenOnIntegration() reruns integration's tests on the PR's
    names): a contest on an element integration never contested forcing another entry with two
    candidates onto the other one.

    Circles r 0.3 at y 0.6: A at (-1.85, 0.6), both crossings on L (a_left at -2.1328, a twin of
    two); E at (-1.2, 0.6), one crossing on L (b_left at -1.4828, a lone one; its other on M).
    One edit: A moved to (2.9, 0.6), so its left crossing stays on R at 2.6172 and its right one
    leaves the Pad's end (x 3): a_left's element moved, its twin count 2 -> 1. E moved to
    (-1.525, 0.6): both its crossings on L now, its left one P at -1.8078 (0.325 from a_left's
    old place and from b_left's), its right one Q at -1.2422 (0.241 from b_left's old place).
    a_left follows A's left crossing or breaks; b_left is E's left crossing: it follows P or
    breaks, never Q."""

    REFS = ("a_left", "b_left")
    CIRCLES = ((-1.85, CY), (-1.2, CY))
    BEFORE = {"a_left": (-1.85 - HH, 0.5), "b_left": (-1.2 - HH, 0.5)}

    def after(self, name):
        if name == "a_left":
            return OwnOrBroken(self.place(2.9 - HH, 0.5))
        return OwnOrBroken(self.place(-1.525 - HH, 0.5))

    def change(self, doc):
        self.moveCircle(0, 2.9, CY)
        self.moveCircle(1, -1.525, CY)


class R2jForcedOntoTwinTwoOwners(R2jForcedOntoTwinOneOwner):
    """The control: one datum point each."""

    ONE_OWNER = False


class R2jForcedOntoTwinSwapped(R2jForcedOntoTwinOneOwner):
    """b_left attached, a_left external."""

    REFS = ("b_left", "a_left")


HA = (R * R - 0.28**2) ** 0.5  # half chord of a circle r 0.3 centred at y 0.78
HE = (R * R - 0.01**2) ** 0.5  # half chord of a circle r 0.3 centred at y 0.51


class R2jForcedPickOneOwner(Base):
    """R2jForcedOntoTwin with tier 3's nearest within reach for a_left. Circles r 0.3: A at
    (-1.70, 0.78), two shallow crossings of L (a_left at -1.70 - HA = -1.8078, its twin 0.216 to
    the right); E at (-1.15, 0.51), one crossing on L (b_left at -1.4498, a lone one; its other
    on M). One edit: A moved to (2.95, 0.78) (its left crossing on R at 2.8422, its right one off
    the Pad's end x 3: a_left's element moved, its twin count 2 -> 1); E moved to (-1.3582, 0.51):
    both crossings on L, its left one P at -1.6580 (0.150 from a_left's old place: tier 3's clear
    nearest for a_left, the next 0.750 away), its right one Q at -1.0584. b_left's old place is
    0.208 from P and 0.392 from Q: no clear nearest, so b_left keeps E's two crossings, tier 1's
    survivors, for the matching. a_left follows A's left crossing or breaks; b_left (E's left
    crossing) follows P or breaks, never Q. Where a_left's broken pick P contests the crossing,
    the matching forces b_left onto Q."""

    REFS = ("a_left", "b_left")
    CIRCLES = ((-1.70, 0.78), (-1.15, 0.51))
    BEFORE = {"a_left": (-1.70 - HA, 0.5), "b_left": (-1.15 - HE, 0.5)}

    def after(self, name):
        if name == "a_left":
            return OwnOrBroken(self.place(2.95 - HA, 0.5))
        return OwnOrBroken(self.place(-1.3582 - HE, 0.5))

    def change(self, doc):
        self.moveCircle(0, 2.95, 0.78)
        self.moveCircle(1, -1.3582, 0.51)


class R2jForcedPickTwoOwners(R2jForcedPickOneOwner):
    """The control: one datum point each."""

    ONE_OWNER = False


class R2jForcedPickSwapped(R2jForcedPickOneOwner):
    """b_left attached, a_left external."""

    REFS = ("b_left", "a_left")
