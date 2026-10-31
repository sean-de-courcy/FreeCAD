# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2bs (ops#468): the pieces of a closed edge keep the maker's order (decision 204).
A disk (a pad of a circle) cut by through-all slots (pockets of strips across it): the top and the
bottom rim circles are cut into arcs, edge twins on a closed first-source edge. The edits turn the
disk's sketch (the rims' seam moves), move or widen a slot (moved placement or redrawn lines), or
add a slot's effect, alone or composed. References: the arcs of both rims."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, ScenarioError, edge

V = App.Vector


def refs(angles):
    return tuple(f"{k}_{int(a)}" for k in ("top", "bot") for a in angles)


class SlottedDisk(Scenario):
    """A pad of a circle of radius 10 about the origin, 20 high; through-all pockets of strips
    (phi: the strip's direction in degrees about Z, d: its offset across, w: its half width) from
    the top. References `top_<a>` and `bot_<a>`: the arc of the top (bottom) rim circle that holds
    the point at angle a degrees at the start. An arc is BROKEN where the slots cover all of it."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2bs"
    TIER = "F"
    SIZE = 20
    SCALE = 1.0
    R, H = 10.0, 20.0
    additive = False  # True: the strips are pads 3 high from the top plane (fuse), not pockets
    redraw = False  # True: the strips' lines are redrawn in global coordinates, no placement
    # state: (turn of the disk's sketch in degrees, ((phi, d, w), ...))
    start = (0.0, ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0)))
    end = (0.0, ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0)))
    angles = (45.0, 135.0, 225.0, 315.0)
    REFS = refs(angles)
    startShift = 0.0  # the whole model's translation along X (the disk's and the strips' sketches)
    endShift = 0.0
    endRot = 0.0  # the whole model's turn about Z in degrees (the end state's turn and strips include it)


    # -- geometry ------------------------------------------------------------------------------
    @staticmethod
    def _covered(t, slots, R):
        for phi, d, w in slots:
            if abs(R * math.sin(math.radians(t - phi)) - d) < w:
                return True
        return False

    def _arcOf(self, t, slots):
        """The angular extent (lo, hi) of the arc through angle t, scanned at 0.02 degrees."""
        lo = hi = t
        for _ in range(18000):
            if self._covered(lo - 0.02, slots, self.R):
                break
            lo -= 0.02
        for _ in range(18000):
            if self._covered(hi + 0.02, slots, self.R):
                break
            hi += 0.02
        return lo, hi

    def expectation(self, name):
        kind, a = name.split("_")
        t0 = float(a)
        s = self.scale
        z = (self.H if kind == "top" else 0.0) * s

        def make():
            _, slots = self.state
            t = t0 + self.rot
            point = V(
                (self.shift + self.R * math.cos(math.radians(t))) * s,
                self.R * math.sin(math.radians(t)) * s,
                z,
            )
            if not self._covered(t, slots, self.R):
                return edge(curve="circle", contains=point)
            lo, hi = self._arcOf(t0, self.start[1])
            lo, hi = lo + self.rot, hi + self.rot
            probe = lo
            while probe <= hi:
                if not self._covered(probe, slots, self.R):
                    raise ScenarioError(f"{name}: its arc is partly covered, ambiguous")
                probe += 0.5
            return BROKEN

        return make

    # -- the model -----------------------------------------------------------------------------
    def _setSlot(self, sketch, spec, before=None, beforeShift=None):
        """Place a strip's sketch. Moved placement mode: only the placement changes unless the
        half width does (then the lines are redrawn). Redraw mode: the lines are redrawn in global
        coordinates when the strip changes at all."""
        s = self.scale
        phi, d, w = spec
        if before == spec and beforeShift == self.shift:
            return
        L = 2.0 * self.R
        local = [(-L, -w), (L, -w), (L, w), (-L, w)]
        if self.redraw:
            c, sn = math.cos(math.radians(phi)), math.sin(math.radians(phi))
            pts = [
                V((x * c - (y + d) * sn + self.shift) * s, (x * sn + (y + d) * c) * s, 0) for x, y in local
            ]
            sketch.Placement = App.Placement(V(0, 0, self.H * s), App.Rotation())
        else:
            pts = [V(x * s, y * s, 0) for x, y in local]
            off = V((self.shift - d * math.sin(math.radians(phi))) * s, d * math.cos(math.radians(phi)) * s, 0)
            sketch.Placement = App.Placement(
                V(0, 0, self.H * s) + off, App.Rotation(V(0, 0, 1), phi)
            )
            if before is not None and before[2] == w:
                return
        lines = [Part.LineSegment(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        if sketch.GeometryCount == 4:
            sketch.Geometry = lines
        else:
            sketch.addGeometry(lines, False)

    def apply(self, before=None, beforeShift=None):
        turn, slots = self.state
        self.disk.Placement = App.Placement(
            V(self.shift * self.scale, 0, 0), App.Rotation(V(0, 0, 1), turn)
        )
        for i, (sketch, spec) in enumerate(zip(self.slotSketches, slots)):
            self._setSlot(sketch, spec, before[1][i] if before else None, beforeShift)

    def build(self, doc):
        s = self.scale
        self.state = self.start
        self.shift = self.startShift
        self.rot = 0.0
        body = doc.addObject("PartDesign::Body", "Body")
        self.disk = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(self.disk)
        self.disk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), self.R * s), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.disk
        pad.Length = self.H * s
        self.slotSketches = []
        pocket = None
        for i, _ in enumerate(self.start[1]):
            sketch = doc.addObject("Sketcher::SketchObject", f"Slot{i}")
            body.addObject(sketch)
            self.slotSketches.append(sketch)
            self._setSlot(sketch, self.start[1][i])
            if self.additive:
                pocket = body.newObject("PartDesign::Pad", f"Bar{i}")
                pocket.Profile = sketch
                pocket.Length = 3.0 * s
            else:
                pocket = body.newObject("PartDesign::Pocket", f"Pocket{i}")
                pocket.Profile = sketch
                pocket.Type = 1
        self.disk.Placement = App.Placement(
            V(self.shift * s, 0, 0), App.Rotation(V(0, 0, 1), self.start[0])
        )
        doc.recompute()
        for name in self.REFS:
            expect = self.expectation(name)
            point = body.newObject("PartDesign::Point", name)
            point.AttachmentSupport = [(pocket, self.names(pocket, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect)
        doc.recompute()

    def edit(self, doc):
        before, beforeShift = self.state, self.shift
        self.state = self.end
        self.shift = self.endShift
        self.rot = self.endRot
        self.apply(before, beforeShift)
        doc.recompute()


F4 = ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0))  # four arcs at 45, 135, 225, 315


class Turn90(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; the sketch turned 90 degrees: the seam goes from slot to slot."
    end = (90.0, F4)


class Turn30(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; turned 30 degrees: the seam goes into the arc at 45 (its arc becomes two edges)."
    end = (30.0, F4)


class Turn180(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; turned 180 degrees."
    end = (180.0, F4)


class Turn270Redrawn(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs, strips redrawn; turned 270 degrees."
    redraw = True
    end = (270.0, F4)


class SlotMovedKeepsAll(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; the first strip moves to offset 1 and the disk turns 90: every arc stays."
    end = (90.0, ((0.0, 1.0, 2.0), (90.0, 0.0, 2.0)))


class SlotMovedKeepsAllRedrawn(SlotMovedKeepsAll):
    __doc__ = SlotMovedKeepsAll.__doc__ + " The strips are redrawn."
    redraw = True


class SlotsWiden(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; the first strip widens to 4 (every arc shrinks, none vanishes)."
    end = (0.0, ((0.0, 0.0, 4.0), (90.0, 0.0, 2.0)))


class SlotsWidenTurned(SlottedDisk):
    __doc__ = SlottedDisk.__doc__ + " Four arcs; the first strip widens to 4 and the disk turns 90."
    end = (90.0, ((0.0, 0.0, 4.0), (90.0, 0.0, 2.0)))


class TwoArcsOneVanishes(SlottedDisk):
    """Two arcs (a strip across the middle), a second strip off the disk that moves onto the
    upper arc and covers all of it."""

    start = (0.0, ((0.0, 0.0, 3.0), (0.0, 20.0, 6.5)))
    end = (0.0, ((0.0, 0.0, 3.0), (0.0, 9.0, 6.5)))
    angles = (90.0, 270.0)
    REFS = refs(angles)


class TwoArcsOneVanishesTurned(TwoArcsOneVanishes):
    __doc__ = TwoArcsOneVanishes.__doc__ + " And the disk turned 90 degrees."
    end = (90.0, ((0.0, 0.0, 3.0), (0.0, 9.0, 6.5)))


class FourToThreeArcs(SlottedDisk):
    """Four arcs; a third strip, off the disk, moves onto the arc at 135 and covers it; the disk
    turns 90 degrees."""

    start = (0.0, ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0), (45.0, 20.0, 2.0)))
    end = (90.0, ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0), (45.0, 9.0, 2.0)))


class FourToThreeArcsNoTurn(FourToThreeArcs):
    end = (0.0, ((0.0, 0.0, 2.0), (90.0, 0.0, 2.0), (45.0, 9.0, 2.0)))


class ArcSplitBySlot(SlottedDisk):
    """Two arcs (a strip across the middle); a second strip off the disk moves to cut each arc in
    two (the reference on the larger piece); the disk turns 90 degrees."""

    start = (0.0, ((0.0, 0.0, 3.0), (90.0, 20.0, 1.0)))
    end = (90.0, ((0.0, 0.0, 3.0), (90.0, 3.0, 1.0)))
    angles = (60.0, 270.0)
    REFS = refs(angles)


class ArcSplitBySlotNoTurn(ArcSplitBySlot):
    end = (0.0, ((0.0, 0.0, 3.0), (90.0, 3.0, 1.0)))


class SixArcs(SlottedDisk):
    """Six arcs: three strips at 0, 60 and 120 degrees (half width 1.5), turned 60 degrees (the
    seam from one slot into another)."""

    start = (0.0, ((0.0, 0.0, 1.5), (60.0, 0.0, 1.5), (120.0, 0.0, 1.5)))
    end = (60.0, ((0.0, 0.0, 1.5), (60.0, 0.0, 1.5), (120.0, 0.0, 1.5)))
    angles = (30.0, 90.0, 150.0, 210.0, 270.0, 330.0)
    REFS = refs(angles)


class SixArcsTurn15(SixArcs):
    __doc__ = SixArcs.__doc__ + " Turned 15 instead (the seam into the arc at 30)."
    end = (15.0, ((0.0, 0.0, 1.5), (60.0, 0.0, 1.5), (120.0, 0.0, 1.5)))


class SixArcsWidenTurned(SixArcs):
    __doc__ = SixArcs.__doc__ + " And the strip at 120 widened to 3."
    end = (60.0, ((0.0, 0.0, 1.5), (60.0, 0.0, 1.5), (120.0, 0.0, 3.0)))


class SixArcsRedrawn(SixArcsWidenTurned):
    redraw = True


# Two parallel strips (y 3..7 and y -7..-3): arcs at 90 and 270 and, between the strips, the
# middle arcs at 0 and 180, twins (both touch the same two strip faces). The seam at 30 (turn 30)
# is inside the first strip's window.
P2 = ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0))
P3 = ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0), (90.0, -20.0, 2.0))


class PairStrips(SlottedDisk):
    """Two parallel strips (y 3..7 and y -7..-3): the middle arcs at 0 and 180 are twins (they
    touch the same two strip faces). The sketch starts turned 30 (the seam inside a strip)."""

    start = (30.0, P2)
    end = (30.0, P2)
    angles = (0.0, 90.0, 180.0, 270.0)
    REFS = refs(angles)


class PairStripsTurn210(PairStrips):
    __doc__ = PairStrips.__doc__ + " Turned to 210 (the seam into the other strip: the order of the middle arcs flips)."
    end = (210.0, P2)


class PairStripsTurn330(PairStrips):
    __doc__ = PairStrips.__doc__ + " Turned to 330."
    end = (330.0, P2)


class PairStripsTurn150(PairStrips):
    __doc__ = PairStrips.__doc__ + " Turned to 150 (the order of the middle arcs is unchanged)."
    end = (150.0, P2)


class PairStripsTurn210Redrawn(PairStripsTurn210):
    redraw = True


class PairStripsTurn210Widen(PairStrips):
    __doc__ = PairStrips.__doc__ + " Turned to 210, strips widened to 2.5 (the arcs shrink)."
    end = (210.0, ((0.0, 5.0, 2.5), (0.0, -5.0, 2.5)))


class PairStripsWidenOnly(PairStrips):
    __doc__ = PairStrips.__doc__ + " Strips widened to 2.5."
    end = (30.0, ((0.0, 5.0, 2.5), (0.0, -5.0, 2.5)))


class PairStripsMovedOnly(PairStrips):
    __doc__ = PairStrips.__doc__ + " The strips move to 5.5 and -4.5."
    end = (30.0, ((0.0, 5.5, 2.0), (0.0, -4.5, 2.0)))


class PairStripsMovedTurned(PairStrips):
    __doc__ = PairStrips.__doc__ + " The strips move to 5.5 and -4.5 and the disk turns to 210."
    end = (210.0, ((0.0, 5.5, 2.0), (0.0, -4.5, 2.0)))


class PairStripsRightVanishes(PairStrips):
    __doc__ = PairStrips.__doc__ + " A third strip (x 7.5..11.5) moves onto the arc at 0: it vanishes, one middle arc is left."
    start = (30.0, P3)
    end = (30.0, ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0), (90.0, -9.5, 2.0)))


class PairStripsRightVanishesTurned(PairStripsRightVanishes):
    __doc__ = PairStripsRightVanishes.__doc__ + " And the disk turns to 210."
    end = (210.0, ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0), (90.0, -9.5, 2.0)))


class PairStripsLeftVanishesTurned(PairStrips):
    __doc__ = PairStrips.__doc__ + " A third strip (x -11.5..-7.5) moves onto the arc at 180: it vanishes; the disk turns to 210."
    start = (30.0, ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0), (90.0, 20.0, 2.0)))
    end = (210.0, ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0), (90.0, 9.5, 2.0)))


class PairStripsTranslated20(PairStrips):
    __doc__ = PairStrips.__doc__ + " The whole model (disk and strips) slides 20 along X, the twins' spacing: the arc at 180 ends where the arc at 0 was."
    endShift = 20.0


class PairStripsTranslated20Turned(PairStrips):
    __doc__ = PairStrips.__doc__ + " Slides 20 along X and the disk turns to 210."
    endShift = 20.0
    end = (210.0, P2)


class PairStripsTranslated(PairStrips):
    __doc__ = PairStrips.__doc__ + " The whole model slides 7 along X."
    endShift = 7.0


class PairStripsTranslated20Redrawn(PairStripsTranslated20):
    redraw = True


# A thin bar (0.1 wide) between two strips: the middle arcs at 0 and 180 are 0.6 degrees long.
THIN = ((0.0, 2.05, 2.0), (0.0, -2.05, 2.0))


class ThinBar(PairStrips):
    """Two parallel strips (y 0.05..4.05 and y -4.05..-0.05) leave a bar 0.1 wide: its two arcs at
    0 and 180 are 0.6 degrees long, twins. The sketch starts turned 10 (the seam inside a strip)."""

    start = (10.0, THIN)
    end = (10.0, THIN)


class ThinBarTurned(ThinBar):
    __doc__ = ThinBar.__doc__ + " Turned to 190 (the other strip: the order of the arcs flips)."
    end = (190.0, THIN)


class ThinBarTurnedMoved(ThinBar):
    __doc__ = ThinBar.__doc__ + " Turned to 190 and the strips move to 2.1 and -2.1 (the bar is 0.2 wide)."
    end = (190.0, ((0.0, 2.1, 2.0), (0.0, -2.1, 2.0)))


class ThinBarMovedOnly(ThinBar):
    __doc__ = ThinBar.__doc__ + " The strips move to 2.1 and -2.1."
    end = (10.0, ((0.0, 2.1, 2.0), (0.0, -2.1, 2.0)))


class BarOneSideOnlyTurned(PairStrips):
    __doc__ = PairStrips.__doc__ + " The two strips swap places (first at -5, second at 5) and the disk turns to 210."
    end = (210.0, ((0.0, -5.0, 2.0), (0.0, 5.0, 2.0)))


R2 = ((0.0, 5.0, 2.0), (0.0, -5.0, 2.0))


class PairStripsRigid180(PairStrips):
    __doc__ = PairStrips.__doc__ + " The whole model (disk and strips) turns 180 about Z: the arcs swap places."
    endRot = 180.0
    end = (210.0, ((180.0, 5.0, 2.0), (180.0, -5.0, 2.0)))


class PairStripsRigid90(PairStrips):
    __doc__ = PairStrips.__doc__ + " The whole model turns 90 about Z."
    endRot = 90.0
    end = (120.0, ((90.0, 5.0, 2.0), (90.0, -5.0, 2.0)))


class PairStripsRigid180Redrawn(PairStripsRigid180):
    redraw = True


class PairStripsRigid180Shifted(PairStrips):
    __doc__ = PairStrips.__doc__ + " The whole model turns 180 about Z and slides 20 along X: the arc at 180 ends where the arc at 0 was."
    endRot = 180.0
    endShift = 20.0
    end = (210.0, ((180.0, 5.0, 2.0), (180.0, -5.0, 2.0)))


class FusedPairStrips(PairStrips):
    """Two bars (y 3..7 and y -7..-3, 3 high) padded from the top plane across the disk: the
    top rim circle is split where the bars' sides cross it. Starts turned 30."""

    additive = True


class FusedPairStripsTurn210(FusedPairStrips):
    end = (210.0, P2)


class FusedPairStripsTurn330(FusedPairStrips):
    end = (330.0, P2)


class FusedPairStripsMovedTurned(FusedPairStrips):
    end = (210.0, ((0.0, 5.5, 2.0), (0.0, -4.5, 2.0)))


class FusedF4Turn90(SlottedDisk):
    """Four bars' worth of arcs (two crossing bars, fused): turned 90."""

    additive = True
    end = (90.0, F4)


class FusedF4Turn180(FusedF4Turn90):
    end = (180.0, F4)
