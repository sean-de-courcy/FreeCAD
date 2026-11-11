# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2hs: review pr390-r2hs probes of the twin clause's T1'' test whatever D2 says (model of review390r2gb.py)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
D = 0.05**0.5
R = 0.3


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2hs"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    HOLES = ((-1, -2, 1, 2),)
    edited = False
    ONE_OWNER = False

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
        if self.ONE_OWNER:
            # One owner holding both references: a sketch attached at the first, the second its
            # external vertex (the forced matching runs over both)
            first, second = self.REFS
            subs = [self.names(pocket, self.place(*self.BEFORE[n]))[0] for n in self.REFS]
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[0])]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subs[1])
            self.ref(first, probe, "AttachmentSupport", self.expectation(first), Attached())
            self.ref(second, probe, "ExternalGeometry", self.expectation(second))
        else:
            for name in self.REFS:
                point = body.newObject("PartDesign::Point", "On" + name)
                sub = self.names(pocket, self.place(*self.BEFORE[name]))[0]
                point.AttachmentSupport = [(pocket, sub)]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def after(self, name):
        """The expectation on the edited model (a predicate, BROKEN, or OwnOrBroken)."""
        raise NotImplementedError

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            return self.after(name)

        return expect

    def addCircle(self, x, y, r=R):
        self.hole.addGeometry(m.circle(self.S(x), self.S(y), self.S(r)), False)

    def redrawCircle(self, index, x, y, r=R):
        self.hole.delGeometry(index)
        self.addCircle(x, y, r)

    def moveCircle(self, index, x, y):
        geometry = self.hole.Geometry
        geometry[index].Center = V(self.S(x), self.S(y), 0)
        self.hole.Geometry = geometry

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class R2hsLoneMovedOffNewCircleAtPlace(Base):
    """A lone crossing (twinCount 1; the circle at (-2.9, 0.7) crosses the Pad's far edge y 0.5 once
    on L, at -2.9 + sqrt(0.05), its other crossing is beyond the Pad's end x -3). One edit: A moves
    clear to (-2, 1.5) and a new circle C (new geometry ID) is drawn at A's old place. A still
    exists, its crossing is gone; C's crossing at the saved place is another circle's. Must break."""

    REFS = ("only",)
    CIRCLES = ((-2.9, 0.7),)
    BEFORE = {"only": (-2.9 + D, 0.5)}

    def after(self, name):
        return BROKEN

    def change(self, doc):
        self.moveCircle(0, -2, 1.5)
        self.addCircle(-2.9, 0.7)


class R2hsLoneRedrawnInPlace(Base):
    """The lone crossing's circle deleted and drawn again where it was: policy D re-binds it
    (round 2f: quiet or warned)."""

    REFS = ("only",)
    CIRCLES = ((-2.9, 0.7),)
    BEFORE = {"only": (-2.9 + D, 0.5)}

    def after(self, name):
        return self.place(*self.BEFORE[name])

    def change(self, doc):
        self.redrawCircle(0, -2.9, 0.7)


class R2hsTwinRedrawnAlone(Base):
    """One circle only (no sibling): A (-2, 0.7) deleted and drawn again where it was. Policy D
    (I-P1): a redraw in the same sketch is re-bound; decision 227 accepts that a twin-saved circle
    redrawn in place breaks. The expectation is the I-P1 one (follow); a break is right -> loud."""

    CIRCLES = ((-2, 0.7),)

    def after(self, name):
        return self.place(*self.BEFORE[name])

    def change(self, doc):
        self.redrawCircle(0, -2, 0.7)


class R2hsTwinRedrawnNewIdThenSiblingMoves(Base):
    """A (-2, 0.7) redrawn in place and, in the same edit, B (2, 0.7) moved to (1.5, 0.7) (its
    crossings stay on R at 1.5 -+ D... B's first crossing at 1.5 - D = 1.28 is on the fill piece M,
    its second on R at 1.72). The references are on A's crossings: both follow the redraw or break,
    never B's."""

    CIRCLES = ((-2, 0.7), (2, 0.7))

    def after(self, name):
        return OwnOrBroken(self.place(*self.BEFORE[name]))

    def change(self, doc):
        self.redrawCircle(0, -2, 0.7)
        self.moveCircle(0, 1.5, 0.7)  # B is index 0 now


class R2hsMovedWithNewAtOwnPlace(Base):
    """A (-2, 0.7) and B (-1.3, 0.7) (A's crossings at -2.236 and -1.764; B's at -1.524 and
    -1.076, apart). One edit: A moves to (-2.5, 0.7), B is deleted and a new circle C is drawn at
    A's old place (-2, 0.7). A still exists with its crossings at -2.736 and -2.264 (tier 1's
    survivors); C's lie at the saved places. Each reference follows A's own crossing (shifted by
    -0.5) or breaks; never C's."""

    CIRCLES = ((-2, 0.7), (-1.3, 0.7))

    def after(self, name):
        return OwnOrBroken(self.place(self.BEFORE[name][0] - 0.5, 0.5))

    def change(self, doc):
        self.moveCircle(0, -2.5, 0.7)
        self.hole.delGeometry(1)
        self.addCircle(-2, 0.7)


class R2hsMovedLittleWithNewOverlapping(Base):
    """Profile regions 4 (batch 2's R1, the control of R2hsMovedWithNewAtOwnPlace): A (-2, 0.7)
    moves 0.1 to (-2.1, 0.7) and a new circle C is drawn at (-1.6, 0.7). A and C overlap above
    the Pad only (y 0.53 to 0.87), so the whole sketch turns from loops into regions and names its
    faces anew; each of A's crossings is still the nearest to its saved place (0.1 away, the other
    0.35 or more) and should follow it: the source twin's offset among A's two crossings is the
    saved one. On 1b273122d5's build `second` follows (tier 3) and `first` breaks before the
    tie-break with evidence `ambiguous` (loud)."""

    def after(self, name):
        return self.place(self.BEFORE[name][0] - 0.1, 0.5)

    def change(self, doc):
        self.moveCircle(0, -2.1, 0.7)
        self.addCircle(-1.6, 0.7)


class R2hsMovedOffNewCircleNearPlace(Base):
    """R2gbMovedOffNewCircleAtPlace with the new circle C drawn a little off A's old place
    (OFFSET along x): its crossings lie near the saved places, not at them (tier 3's nearest, no
    longer XP). A still exists (moved to (-1.1, 0.7)): second's crossing is gone and must break;
    first follows A's crossing at -1.1 - D or breaks."""

    CIRCLES = ((-2, 0.7), (2, 0.7))
    OFFSET = 0.03

    def after(self, name):
        if name == "first":
            return OwnOrBroken(self.place(-1.1 - D, 0.5))
        return BROKEN

    def change(self, doc):
        self.moveCircle(0, -1.1, 0.7)
        self.addCircle(-2 + self.OFFSET, 0.7)


class R2hsMovedOffNewCircleNear10(R2hsMovedOffNewCircleNearPlace):
    OFFSET = 0.1


class R2hsMovedOffNewCircleNear30(R2hsMovedOffNewCircleNearPlace):
    OFFSET = 0.3


class R2hsMovedOffNewCircleNearMinus30(R2hsMovedOffNewCircleNearPlace):
    OFFSET = -0.3


HH = (R * R - 0.1**2) ** 0.5  # half chord of a circle r 0.3 centred 0.1 above the edge y 0.5


class R2hsFreedElementTwoOwners(Base):
    """Two references of one Pocket that want the same element. Circles (y 0.6, r 0.3): A at
    (-1.82, 0.6), two crossings of L (twins); B at (-1.2, 0.6), one crossing of L at -1.4828 (a lone
    one; the other on the fill's piece M); C at (2, 0.6), unchanged. a_right is A's right crossing
    (-1.5372), b_left is B's (-1.4828, 0.054 away). One edit: B deleted, A deleted and drawn again
    where it was. a_right's crossing is drawn again at its place (follow, or break: decision 227);
    b_left's circle is gone: it breaks (policy D), the crossing 0.054 away being another circle's."""

    REFS = ("a_right", "b_left")
    CIRCLES = ((-1.82, 0.6), (-1.2, 0.6), (2, 0.6))
    BEFORE = {"a_right": (-1.82 + HH, 0.5), "b_left": (-1.2 - HH, 0.5)}

    def after(self, name):
        if name == "a_right":
            return OwnOrBroken(self.place(*self.BEFORE[name]))
        return BROKEN

    def change(self, doc):
        self.hole.delGeometry(1)
        self.redrawCircle(0, -1.82, 0.6)


class R2hsFreedElementOneOwner(R2hsFreedElementTwoOwners):
    """The same edit with both references in one owner (a sketch attached at a_right, b_left its
    external vertex): the forced matching runs over both. On a build where a_right's pick (drawn
    again) and b_left's nearest are the same crossing they contest it; once a_right breaks before
    the matching (the twin clause's T1'' test), b_left holds the crossing alone."""

    ONE_OWNER = True
