# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corpus cases (class A, ops#468): fork PR 390 round 2d's fix-trace review (pr390-r2dfs). Round 2d's
literal stop in solveOwner's moved-exact-hit check breaks a moved exact hit on a crossing-role name
(`in` / `out`) with no twin now, or a twin group whose count changed. These cases aim it at other
shapes than a pad's top edge crossed by one round hole.
Model E: a plate 200 x 100 x 5 (scale 3 by default), its front top edge (y = 0, z = 5), pockets
through all (Midplane) of cutters whose boundary crosses that edge, a datum point on each crossing
vertex. A cutter is a `circle` (r 1, centre y 0.5), an `ellipse` (2 x 1), a `rect` (3 x 2, y -0.5 to
1.5), a `slot` (an obround 3 + 2 long, 2 wide) or a `wave` (a closed spline through points
alternating +-1 about the edge: n crossings of one face). Each expectation is the crossing of the
same cutter, on the same side (or the same ordinal from the left), on the edited model, else BROKEN.
Edits: `flip` (the profile's front line drawn the other way, the side role's switch point, I-A6),
`dx` (a cutter moved along the edge by its geometry), `redraw` (deleted and drawn again)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)
SIDES = {
    "circle": {"L": -HALF, "R": HALF},
    "ellipse": {"L": -2 * HALF, "R": 2 * HALF},
    "rect": {"L": -1.5, "R": 1.5},
    "slot": {"L": -(1.5 + HALF), "R": 1.5 + HALF},
}


def drawnTheOtherWay(sketch, index=0):
    """Line `index` of the sketch drawn the other way, its geometry id kept."""
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


def waveCurve(cx, n, k):
    """The spline through n + 1 points alternating +1, -1 about y = 0, from x = cx - n / 2."""
    points = [V((cx - n / 2 + i) * k, (1 if i % 2 == 0 else -1) * k, 0) for i in range(n + 1)]
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve, points


def waveCrossings(cx, n):
    """Where the wave crosses y = 0 (unscaled), by bisection on the spline."""
    curve, _ = waveCurve(cx, n, 1.0)
    low, high = curve.FirstParameter, curve.LastParameter
    steps = 4000
    found = []
    previous = curve.value(low).y
    for i in range(1, steps + 1):
        u = low + (high - low) * i / steps
        value = curve.value(u).y
        if (previous < 0) != (value < 0):
            a, b = low + (high - low) * (i - 1) / steps, u
            for _ in range(60):
                mid = (a + b) / 2
                if (curve.value(mid).y < 0) == (curve.value(a).y < 0):
                    a = mid
                else:
                    b = mid
            found.append(curve.value(a).x)
        previous = value
    return found


def cutterGeometry(kind, cx, k, n=4):
    """The sketch geometry of a cutter centred at cx (unscaled), scaled by k."""
    if kind == "circle":
        return [m.circle(cx * k, 0.5 * k, k)]
    if kind == "ellipse":
        return [
            Part.Ellipse(
                V((cx + 2) * k, 0.5 * k, 0), V(cx * k, 1.5 * k, 0), V(cx * k, 0.5 * k, 0)
            )
        ]
    if kind == "rect":
        return m.rectangle((cx - 1.5) * k, -0.5 * k, (cx + 1.5) * k, 1.5 * k)
    if kind == "slot":
        left = Part.ArcOfCircle(
            Part.Circle(V((cx - 1.5) * k, 0.5 * k, 0), V(0, 0, 1), k), math.pi / 2, 3 * math.pi / 2
        )
        right = Part.ArcOfCircle(
            Part.Circle(V((cx + 1.5) * k, 0.5 * k, 0), V(0, 0, 1), k), -math.pi / 2, math.pi / 2
        )
        top = Part.LineSegment(V((cx - 1.5) * k, 1.5 * k, 0), V((cx + 1.5) * k, 1.5 * k, 0))
        bottom = Part.LineSegment(V((cx - 1.5) * k, -0.5 * k, 0), V((cx + 1.5) * k, -0.5 * k, 0))
        return [left, top, right, bottom]
    if kind == "wave":
        curve, points = waveCurve(cx, n, k)
        first, last = points[0], points[-1]
        up = 3 * k
        return [
            curve,
            Part.LineSegment(last, V(last.x, up, 0)),
            Part.LineSegment(V(last.x, up, 0), V(first.x, up, 0)),
            Part.LineSegment(V(first.x, up, 0), first),
        ]
    raise ValueError(kind)


class E(Scenario):
    """Base: `groups` is a tuple of sketches, each a tuple of cutters (kind, centre x, [n])."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M1", "E1", "E4", "X4:600")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2dfs"
    TIER = "F"
    SIZE, SCALE = 200, 3
    groups = ((("circle", 100.0),),)
    plateX = (0.0, 200.0)
    flip = False
    dx = 0.0
    top = 5.0
    taller = None  # the pad's new length
    mover = (0, 0)  # the cutter moved: (group, index)
    redraw = False
    steps = ("edit",)
    instances = (0.0,)  # the x offset of each copy of the pocket (a pattern), the first the original

    # the crossings of a cutter now: label -> unscaled x
    def crossingsOf(self, g, c):
        kind, cx = self.groups[g][c][0], self.pos[(g, c)]
        if kind == "wave":
            xs = waveCrossings(cx, self.groups[g][c][2])
            return {f"c{i}": x for i, x in enumerate(xs)}
        return {label: cx + d for label, d in SIDES[kind].items()}

    def copyX(self, j, x):
        return x + self.instances[j]

    def place(self, name):
        """(copy j, group, cutter, label) of a reference name `g0c0_L@1`."""
        head, _, j = name.partition("@")
        cut, label = head.split("_")
        return int(j or 0), int(cut[1]), int(cut[3]), label

    def expected(self, name):
        j, g, c, label = self.place(name)
        x = self.copyX(j, self.crossingsOf(g, c)[label])
        lo, hi = self.plateX
        return vertex(at=self.s(x, 0, self.top)) if lo + 1e-6 < x < hi - 1e-6 else BROKEN

    def build(self, doc):
        body = m.body(doc)
        lo, hi = self.plateX
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(lo, 0, hi, 100)), body)
        m.pad(body, self.profile, self.s(5))
        self.pos, self.sketches, self.ranges = {}, [], {}
        last = None
        for g, group in enumerate(self.groups):
            geometry = []
            for c, cutter in enumerate(group):
                self.pos[(g, c)] = cutter[1]
                made = cutterGeometry(cutter[0], cutter[1], self.scale, *cutter[2:])
                self.ranges[(g, c)] = (len(geometry), len(geometry) + len(made))
                geometry += made
            sketch = m.sketch(doc, f"Hole{g}", geometry, body)
            pocket = body.newObject("PartDesign::Pocket", f"Pocket{g}")
            pocket.Profile, pocket.Type, pocket.Midplane = sketch, 1, True
            self.sketches.append(sketch)
            last = pocket
        last = self.copies(doc, body, last)
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name.replace("@", "_"))
            point.AttachmentSupport = [(last, self.names(last, self.expected(name))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda n=name: self.expected(n), Attached())
        doc.recompute()

    def copies(self, doc, body, last):
        return last

    def moveCutter(self, doc):
        g, c = self.mover
        a, b = self.ranges[(g, c)]
        sketch = doc.getObject(f"Hole{g}")
        if self.redraw:
            for index in range(b - 1, a - 1, -1):
                sketch.delGeometry(index)
            kind, _ = self.groups[g][c][0], 0
            sketch.addGeometry(
                cutterGeometry(kind, self.pos[(g, c)] + self.dx, self.scale, *self.groups[g][c][2:]),
                False,
            )
        else:
            geometry = sketch.Geometry
            for index in range(a, b):
                geometry[index].translate(V(self.dx * self.scale, 0, 0))
            sketch.Geometry = geometry
        self.pos[(g, c)] += self.dx

    sketchTurn = False  # the hole sketch turned over (its normal reversed) about the X axis at y = 0.5

    def flipIt(self, doc):
        if self.sketchTurn:
            k = self.scale
            for g in range(len(self.groups)):
                sketch = doc.getObject(f"Hole{g}")
                sketch.Placement = App.Placement(V(0, k, 0), App.Rotation(V(1, 0, 0), 180))
            return
        drawnTheOtherWay(doc.getObject("Profile"))

    def edit(self, doc):
        if self.flip:
            self.flipIt(doc)
        if self.dx:
            self.moveCutter(doc)
        if self.taller:
            doc.getObject("Pad").Length = self.s(self.taller)
            self.top = self.taller
        doc.recompute()

    def flipFirst(self, doc):
        self.flipIt(doc)
        doc.recompute()

    def moveOnly(self, doc):
        self.moveCutter(doc)
        doc.recompute()


def refs(*cutters, copies=1):
    names = []
    for j in range(copies):
        for g, c, labels in cutters:
            for label in labels:
                names.append(f"g{g}c{c}_{label}" + (f"@{j}" if j else ""))
    return tuple(names)


LR = "LR"
WAVE = ("c0", "c1", "c2", "c3")
FLIP_ONLY = dict(flip=True, dx=0.0)


def case(name, base, doc, *mixins, **attrs):
    """A case class `name` of `base` (with the mixins before it) in this module."""
    globals()[name] = type(name, (*mixins, base), dict(attrs, __doc__=doc, __module__=__name__))


def one(kind, cx=100.0, *n):
    return (((kind, cx) + n,),)


# ---- lone crossings: one sketch edge per crossing (a rectangle's sides, a slot's end arcs) ------
case("R2dfsRectMoved", E, "A 3 x 2 rectangle across the edge moved 5 along it: its two side faces each "
     "cross the edge once (lone role-named crossings). Both points follow.",
     groups=one("rect"), REFS=refs((0, 0, LR)), dx=5.0)
case("R2dfsRectMovedSmall", R2dfsRectMoved, "Moved 0.4.", dx=0.4)
case("R2dfsRectMovedOut", R2dfsRectMoved, "At 197, moved 3: the right side leaves the plate; right breaks.",
     groups=one("rect", 197.0), dx=3.0)
case("R2dfsRectFlipMoved", R2dfsRectMoved, "Flipped and moved 5.", flip=True)
case("R2dfsRectFlipOnly", R2dfsRectMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsSlotMoved", E, "An obround across the edge moved 5: its end arcs each cross the edge once.",
     groups=one("slot"), REFS=refs((0, 0, LR)), dx=5.0)
case("R2dfsSlotFlipMoved", R2dfsSlotMoved, "Flipped and moved 5.", flip=True)
case("R2dfsSlotFlipOnly", R2dfsSlotMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsRectSketchTurnedMoved", R2dfsRectMoved, "The hole's sketch turned over (no switch point), moved 3.",
     flip=True, sketchTurn=True, dx=3.0)
case("R2dfsSlotSketchTurnedMoved", R2dfsSlotMoved, "As above, a slot.", flip=True, sketchTurn=True, dx=3.0)

# ---- twin crossings of a round hole, an ellipse; the flip switch point ---------------------------
case("R2dfsCircleMoved", E, "The control: a round hole moved 5 along the edge.",
     REFS=refs((0, 0, LR)), dx=5.0)
case("R2dfsCircleFlipMoved", R2dfsCircleMoved, "Flipped and moved 3: both crossings stay, count kept, "
     "nothing at either old place.", flip=True, dx=3.0)
case("R2dfsCircleFlipMovedFar", R2dfsCircleMoved, "Flipped and moved 40.", flip=True, dx=40.0)
case("R2dfsCircleFlipMovedSmall", R2dfsCircleMoved, "Flipped and moved 0.4.", flip=True, dx=0.4)
case("R2dfsCircleFlipOnly", R2dfsCircleMoved, "Flipped only: each crossing's twin sits at its old place.",
     **FLIP_ONLY)
case("R2dfsCircleFlipThenMove", R2dfsCircleMoved, "Flipped, recomputed, then moved 3.",
     steps=("flipFirst", "moveOnly"), dx=3.0)
case("R2dfsCirclePadTaller", E, "The control: pad 5 -> 8, a round hole's crossings move up together.",
     REFS=refs((0, 0, LR)), taller=8.0)
case("R2dfsCirclePadTallerFlip", R2dfsCirclePadTaller, "Taller and flipped.", flip=True)
case("R2dfsEllipseMoved", E, "An ellipse 4 x 2 moved 5.", groups=one("ellipse"),
     REFS=refs((0, 0, LR)), dx=5.0)
case("R2dfsEllipseFlipMoved", R2dfsEllipseMoved, "Flipped and moved 3.", flip=True, dx=3.0)
case("R2dfsEllipseFlipOnly", R2dfsEllipseMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsEllipseRedrawn", R2dfsEllipseMoved, "Deleted and drawn again 5 along: no names kept by id.",
     AXES=("M1", "E2", "X4:600"), redraw=True)
case("R2dfsEllipsePadTaller", R2dfsCirclePadTaller, "Pad 5 -> 8.", groups=one("ellipse"))

# ---- two holes on one edge -----------------------------------------------------------------------
TWO = ((("circle", 100.0), ("circle", 104.0)),)
NEXT = ((("circle", 100.0), ("circle", 102.0)),)
case("R2dfsTwoHolesMoveA", E, "Two holes in one sketch (two groups of two crossings), the first moved "
     "10 away.", groups=TWO, REFS=refs((0, 0, LR), (0, 1, LR)), dx=-10.0)
case("R2dfsTwoHolesMoveAFlip", R2dfsTwoHolesMoveA, "Flipped as well.", flip=True)
case("R2dfsTwoHolesMoveAOver", R2dfsTwoHolesMoveA, "The first (100) moved 4 next to the second (102).",
     groups=NEXT, dx=4.0)
class UnionOfCircles:
    """Overlapping circles of one sketch cut their union (Onshape's regions; profile regions 3):
    a crossing inside another circle of the same sketch is gone, so its point breaks."""

    def expected(self, name):
        j, g, c, label = self.place(name)
        x = self.crossingsOf(g, c)[label]
        for other in range(len(self.groups[g])):
            if other != c and self.groups[g][other][0] == "circle" and abs(x - self.pos[(g, other)]) < HALF - 1e-9:
                return BROKEN
        return super().expected(name)


case("R2dfsTwoHolesOverlapMerge", R2dfsTwoHolesMoveA, "The first (100) moved 1.5 onto the second (102): "
     "the rims merge, crossings 4 -> 2; the sketch cuts the circles' union (Onshape), so the inner crossings "
     "c0_R and c1_L break (batch 3, R2).", UnionOfCircles, groups=NEXT, dx=1.5)
case("R2dfsTwoHolesOtherSketchMoveA", R2dfsTwoHolesMoveA, "Two pockets, the second hole in another sketch.",
     groups=((("circle", 100.0),), (("circle", 104.0),)), REFS=refs((0, 0, LR), (1, 0, LR)))
case("R2dfsTwoHolesOtherSketchMoveAFlip", R2dfsTwoHolesOtherSketchMoveA, "Flipped as well.", flip=True)
case("R2dfsTwoHolesPadTaller", R2dfsCirclePadTaller, "Pad 5 -> 8.", groups=TWO,
     REFS=refs((0, 0, LR), (0, 1, LR)))

# ---- a wavy cut: one face crossing the edge 3 or 4 times ----------------------------------------
case("R2dfsWaveFourMoved", E, "Four crossings of one face, the wave moved 0.4 (all four stay).",
     groups=one("wave", 100.0, 4), REFS=refs((0, 0, WAVE)), dx=0.4)
case("R2dfsWaveFourMovedFar", R2dfsWaveFourMoved, "Moved 7.", dx=7.0)
case("R2dfsWaveFourFlipMoved", R2dfsWaveFourMoved, "Flipped and moved 0.4.", flip=True)
case("R2dfsWaveFourFlipOnly", R2dfsWaveFourMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsWaveFourPastTheEnd", R2dfsWaveFourMoved, "At 197, moved 2: the last crossing leaves, 4 -> 3.",
     groups=one("wave", 197.0, 4), dx=2.0)
case("R2dfsWaveFourPastTheEndFlip", R2dfsWaveFourPastTheEnd, "Flipped as well.", flip=True)
case("R2dfsWaveFourPadTaller", R2dfsCirclePadTaller, "Pad 5 -> 8.", groups=one("wave", 100.0, 4),
     REFS=refs((0, 0, WAVE)))
case("R2dfsWaveThreeMoved", E, "Three crossings of the wave (and its closing line's own), moved 0.4.",
     groups=one("wave", 100.0, 3), REFS=refs((0, 0, WAVE[:3])), dx=0.4)
case("R2dfsWaveThreeFlipMoved", R2dfsWaveThreeMoved, "Flipped as well.", flip=True)
case("R2dfsWaveThreePadTaller", R2dfsCirclePadTaller, "Pad 5 -> 8.", groups=one("wave", 100.0, 3),
     REFS=refs((0, 0, WAVE[:3])))

# ---- the pad made taller: every crossing at the top moves up, nothing at its old place ----------
case("R2dfsRectPadTaller", R2dfsCirclePadTaller, "A rectangle across the edge, the pad 5 -> 8: two lone "
     "crossings move up.", groups=one("rect"))
case("R2dfsRectPadTallerFlip", R2dfsRectPadTaller, "Taller and flipped.", flip=True)
case("R2dfsSlotPadTaller", R2dfsCirclePadTaller, "A slot, the pad 5 -> 8.", groups=one("slot"))


# ---- copies: a pattern and a mirror --------------------------------------------------------------
class LinearCopies(E):
    """A LinearPattern of 3 occurrences 20 apart of a pocket at 30; the original moved 3, the
    copies follow."""

    abstract = True
    instances = (0.0, 20.0, 40.0)

    def copies(self, doc, body, last):
        pattern = doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [last]
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = self.s(20)
        pattern.Occurrences = 3
        body.addObject(pattern)
        return pattern


class MirroredCopy(E):
    """A plate -100..100, a hole at 30 mirrored across the YZ plane (at -30), the original moved
    to 35, the copy to -35."""

    abstract = True
    plateX = (-100.0, 100.0)

    def copyX(self, j, x):
        return -x if j else x

    def copies(self, doc, body, last):
        mirror = doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirror.Originals = [last]
        mirror.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.addObject(mirror)
        return mirror


THREE = dict(REFS=refs((0, 0, LR), copies=3), dx=3.0)
case("R2dfsLinearCopiesMoved", LinearCopies, "Round holes.", groups=one("circle", 30.0), **THREE)
case("R2dfsLinearCopiesFlip", R2dfsLinearCopiesMoved, "Flipped as well.", flip=True)
case("R2dfsLinearCopiesFlipOnly", R2dfsLinearCopiesMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsLinearRectCopies", LinearCopies, "Rectangles.", groups=one("rect", 30.0), **THREE)
case("R2dfsLinearRectCopiesFlip", R2dfsLinearRectCopies, "Flipped as well.", flip=True)
case("R2dfsLinearRectCopiesPadTaller", R2dfsLinearRectCopies, "Pad 5 -> 8.", dx=0.0, taller=8.0)
MIRROR = dict(REFS=refs((0, 0, LR), copies=2), dx=5.0)
case("R2dfsMirroredMoved", MirroredCopy, "Round hole.", groups=one("circle", 30.0), **MIRROR)
case("R2dfsMirroredFlip", R2dfsMirroredMoved, "Flipped as well.", flip=True)
case("R2dfsMirroredFlipOnly", R2dfsMirroredMoved, "Flipped only.", **FLIP_ONLY)
case("R2dfsMirroredPadTaller", R2dfsMirroredMoved, "Pad 5 -> 8.", dx=0.0, taller=8.0)

# ---- a reopen ------------------------------------------------------------------------------------
REOPEN = dict(steps=("reopen", "edit"))
case("R2dfsCircleReopenThenMove", R2dfsCircleMoved, "Saved, closed, opened, then moved.", Reopens, **REOPEN)
case("R2dfsCircleReopenThenFlipMove", R2dfsCircleFlipMoved, "Reopened, then flipped and moved.", Reopens, **REOPEN)
case("R2dfsRectReopenThenMove", R2dfsRectMoved, "Reopened, then moved.", Reopens, **REOPEN)
case("R2dfsRectMoveThenReopen", R2dfsRectMoved, "Moved, then reopened.", Reopens, steps=("edit", "reopen"))
case("R2dfsRectPadTallerReopen", R2dfsRectPadTaller, "Reopened, then taller.", Reopens, **REOPEN)
case("R2dfsWaveFourReopenThenFlipMove", R2dfsWaveFourFlipMoved, "Reopened, then flipped and moved.", Reopens, **REOPEN)
