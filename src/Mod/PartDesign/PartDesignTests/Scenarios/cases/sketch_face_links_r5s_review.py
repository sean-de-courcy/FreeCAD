# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r5s (class E, E1; ops#264 e2): attacks on a face link's pairing aimed at round 5's
two changes: the place vote's same-side test (`sameSide`, a midpoint normal) and the batch check
that rejects a batch which empties one arc of a loop while another fills.

Every model is designed geometry: a profile padded 10 high, a sketch at z = 0 projecting the pad's
top face, and circles r 1 held by PointOnObject on projected geometry. The outcome is where each
constraint is after the edit (on the new copy of its own line, or the sketch breaks)."""

import math
import random

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]
SQUARE_LINES = [((0, 0), (20, 0)), ((20, 0), (20, 20)), ((20, 20), (0, 20)), ((0, 20), (0, 0))]


def matches(g, spec):
    """spec: ("x"|"y", value, (lo, hi)), ("ends", a, b), ("arc", centre, radius)."""
    if spec[0] == "arc":
        if not hasattr(g, "Radius") or not hasattr(g, "FirstParameter"):
            return False
        return g.Center.isEqual(V(*spec[1], 0), TOL) and abs(g.Radius - spec[2]) < TOL
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius"):
        return False
    s, e = g.StartPoint, g.EndPoint
    if spec[0] == "ends":
        a, b = V(*spec[1], 0), V(*spec[2], 0)
        return (s.isEqual(a, TOL) and e.isEqual(b, TOL)) or (s.isEqual(b, TOL) and e.isEqual(a, TOL))
    axis, value, (lo, hi) = spec
    other = "y" if axis == "x" else "x"
    if not all(abs(getattr(p, axis) - value) < TOL for p in (s, e)):
        return False
    a, b = sorted(getattr(p, other) for p in (s, e))
    return abs(a - lo) < TOL and abs(b - hi) < TOL


def findExternal(sketch, spec):
    found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matches(g, spec)]
    if len(found) < 1:
        raise AssertionError(f"no projected geometry matches {spec}")
    return found[0]


def anchorPoint(spec):
    if spec[0] == "arc":
        return (spec[1][0] + spec[2], spec[1][1])
    if spec[0] == "ends":
        return tuple((a + b) / 2 for a, b in zip(spec[1], spec[2]))
    axis, value, (lo, hi) = spec
    return (value, (lo + hi) / 2) if axis == "x" else ((lo + hi) / 2, value)


def lineSpec(a, b):
    """An axis-aligned line's spec."""
    if abs(a[0] - b[0]) < TOL:
        return ("x", a[0], tuple(sorted((a[1], b[1]))))
    return ("y", a[1], tuple(sorted((a[0], b[0]))))


class HeldBy(Outcome):
    """Each PointOnObject constraint (in the order they were added) names the projected geometry
    `before()[i]` before the edit and `after()[i]` after it, with its circle's centre on it."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        specs = self.before() if scenario.stepName is None else self.after()
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
        if not consumer.isValid():
            return False, consumer.getStatusString()
        if len(cons) != len(specs):
            return False, f"{len(cons)} constraints for {len(specs)} specs"
        for c, spec in zip(cons, specs):
            held = consumer.ExternalGeo[-c.Second - 1]
            if not matches(held, spec):
                return False, f"a constraint is on {held.TypeId} {held}, not {spec}"
            centre = consumer.Geometry[c.First].Center
            if spec[0] == "arc":
                if abs((centre - held.Center).Length - held.Radius) > TOL:
                    return False, f"circle centre at {centre}"
            elif centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
                return False, f"circle centre at {centre}"
        return True, ""


class Review(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5s"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circles_on_geometry",)
    height = 10

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in SQUARE])

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def expectation(self):
        return self.topFace

    def build(self, doc):
        s = self.s
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body)
        pad = m.pad(body, profile, s(self.height))
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        for spec in self.before():
            line = findExternal(sketch, spec)
            x, y = anchorPoint(spec)
            circle = sketch.addGeometry(m.circle(x, y, s(1)), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, s(1)))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldBy(self.before, self.afterEdit))

    def moveLines(self, doc, lines):
        s = self.s
        geometry = doc.Profile.Geometry
        for index, (a, b) in lines.items():
            line = geometry[index]
            line.StartPoint = V(*s(-777, -777), 0)
            line.EndPoint = V(*s(*b), 0)
            line.StartPoint = V(*s(*a), 0)
        doc.Profile.Geometry = geometry

    def addLines(self, doc, points):
        doc.Profile.addGeometry(m.polyline([self.s(*p) for p in points]), False)


# ---- a profile translated; kept / redrawn / flipped lines; a cut (the place vote's side) -----------

SHAPES = {
    "Sq": [(0, 0), (20, 0), (20, 20), (0, 20)],
    "L": [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)],
    "U": [(0, 0), (30, 0), (30, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)],
    "N": [(0, 0), (50, 0), (50, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)],
}


def outLines(points, dx, dy, cut, size=3):
    """The translated profile's lines (start, end), the ends shortened by a cut at the end of
    line `cut` (the corner after it); and the cut line, or None."""
    n = len(points)
    lines = [
        [[points[i][0] + dx, points[i][1] + dy],
         [points[(i + 1) % n][0] + dx, points[(i + 1) % n][1] + dy]]
        for i in range(n)
    ]
    cutLine = None
    if cut is not None:
        i, j = cut, (cut + 1) % n
        a, b = lines[i]
        c, d = lines[j]
        ub = (b[0] - a[0], b[1] - a[1])
        k = math.hypot(*ub)
        newEnd = [b[0] - size * ub[0] / k, b[1] - size * ub[1] / k]
        uc = (d[0] - c[0], d[1] - c[1])
        k = math.hypot(*uc)
        newStart = [c[0] + size * uc[0] / k, c[1] + size * uc[1] / k]
        lines[i][1] = newEnd
        lines[j][0] = newStart
        cutLine = (newEnd, newStart)
    return lines, cutLine


# ---- geometry saved before E1 (no source names) --------------------------------------------------
import os
import re
import tempfile
import zipfile


def reopenWithoutSources(scenario, doc):
    """The document saved, closed and opened again with every external geometry's source name
    removed from its Document.xml (geometry saved by a build before E1)."""
    scenario.folder = tempfile.mkdtemp(prefix="NamingScenario")
    path = os.path.join(scenario.folder, doc.Name + ".FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    xml = files["Document.xml"].decode("utf-8")
    count = 0

    def strip(match):
        nonlocal count
        tag, n = re.subn(r' Source="[^"]*"', "", match.group(0))
        count += n
        return tag

    xml = re.sub(r'<GeoExtension [^>]*Sketcher::ExternalGeometryExtension[^>]*>', strip, xml)
    if count == 0 and hasattr(Sketcher.ExternalGeometryFacade, "Source"):
        raise RuntimeError("no external geometry with a source name in the saved file")
    files["Document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return scenario.openDocument(path)


# ======================================================================================
# review pr384-r5s: attacks on round 5s's changes (face on the left of every loop, the exact swept
# areas, the name-only rule with the common move, the batch check read over place votes)
# ======================================================================================
import os


def polyLines(points):
    n = len(points)
    return [(points[i], points[(i + 1) % n]) for i in range(n)]


class Stretch(Review):
    """A profile (`base` with vertices `moveTo` moved), each line keeps its ID and is moved in
    place, a corner cut by a new line (index n); a circle on each line in `held`."""

    abstract = True
    AXES = ("M8", "E5", "E1")
    base = [(0, 0), (20, 0), (20, 20), (0, 20)]
    moveTo = {}
    cut = None
    size = 4
    held = (0, 1, 2, 3)

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in self.base])

    def newPoints(self):
        pts = [list(p) for p in self.base]
        for i, p in self.moveTo.items():
            pts[i] = list(p)
        return pts

    def before(self):
        lines = polyLines(self.base)
        return [("ends", self.s(*lines[i][0]), self.s(*lines[i][1])) for i in self.held]

    def afterEdit(self):
        lines, _ = outLines(self.newPoints(), 0, 0, self.cut, self.size)
        return [("ends", self.s(*lines[i][0]), self.s(*lines[i][1])) for i in self.held]

    def edit(self, doc):
        lines, cutLine = outLines(self.newPoints(), 0, 0, self.cut, self.size)
        n = len(self.base)
        self.moveLines(doc, {i: (tuple(lines[i][0]), tuple(lines[i][1])) for i in range(n)})
        if cutLine:
            self.addLines(doc, [tuple(cutLine[0]), tuple(cutLine[1])])


def _stretch_cases():
    shapes = {
        "Sq": (
            [(0, 0), (20, 0), (20, 20), (0, 20)],
            {
                "X": {1: (30, 0), 2: (30, 20)},
                "Y": {2: (20, 28), 3: (0, 28)},
                "XY": {1: (30, 0), 2: (30, 28), 3: (0, 28)},
            },
        ),
        "L": (
            [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)],
            {
                "X": {1: (40, 0), 2: (40, 10)},
                "Y": {4: (10, 40), 5: (0, 40)},
                "W": {3: (14, 10), 4: (14, 30)},
            },
        ),
    }
    for sname, (base, stretches) in shapes.items():
        n = len(base)
        for tname, move in stretches.items():
            for cut in [None] + list(range(n)):
                name = "ReviewStretch%s%s%s" % (sname, tname, "NoCut" if cut is None else "Cut%d" % cut)
                globals()[name] = type(
                    name,
                    (Stretch,),
                    {"base": base, "moveTo": move, "cut": cut, "held": tuple(range(n)), "__module__": __name__},
                )


_stretch_cases()


class Plate(Review):
    """An outer square 40 and a square hole (lines 0-3 the outer, 4-7 the hole), padded. The edit
    moves the hole by (hx, hy), the whole plate by (dx, dy), cuts a corner of the outer (`ocut`)
    and/or of the hole (`hcut`); `keep` lines keep their IDs (moved; `flip` swapped ends), the rest
    are deleted and drawn again in `order`, reversed per `rev`; the cut lines are 8 (outer) and 9
    (hole). A circle on each line. Each must be on the moved copy of its own line, or break."""

    abstract = True
    AXES = ("M8", "E5", "E2")
    OUTER = [(0, 0), (40, 0), (40, 40), (0, 40)]
    HOLE = [(15, 15), (25, 15), (25, 25), (15, 25)]
    hx = hy = dx = dy = 0
    ocut = hcut = None
    holeCW = False
    keep = tuple(range(8))
    flip = ()
    order = ()
    rev = ()

    def holePts(self):
        return list(reversed(self.HOLE)) if self.holeCW else list(self.HOLE)

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in self.OUTER]) + m.polygon(
            [self.s(*p) for p in self.holePts()]
        )

    def before(self):
        lines = polyLines(self.OUTER) + polyLines(self.holePts())
        return [("ends", self.s(*a), self.s(*b)) for a, b in lines]

    def _new(self):
        o, oc = outLines([list(p) for p in self.OUTER], self.dx, self.dy, self.ocut, 4)
        h, hc = outLines(
            [list(p) for p in self.holePts()], self.dx + self.hx, self.dy + self.hy, self.hcut, 2
        )
        return o + h, [oc, hc]

    def afterEdit(self):
        lines, _ = self._new()
        return [("ends", self.s(*a), self.s(*b)) for a, b in lines]

    def edit(self, doc):
        lines, cuts = self._new()
        gone = [i for i in range(8) if i not in self.keep]
        doc.Profile.delGeometries(gone)
        kept = {i: k for k, i in enumerate(self.keep)}
        moves = {}
        for i in self.keep:
            a, b = lines[i]
            moves[kept[i]] = (tuple(b), tuple(a)) if i in self.flip else (tuple(a), tuple(b))
        self.moveLines(doc, moves)
        extra = {8: cuts[0], 9: cuts[1]}
        order = list(self.order)
        for i, cutLine in ((8, cuts[0]), (9, cuts[1])):
            if cutLine and i not in order and (i == 8 and self.ocut is not None or i == 9 and self.hcut is not None):
                order.append(i)
        order = [i for i in order if i < 8 or extra[i]]
        for i in order:
            a, b = lines[i] if i < 8 else extra[i]
            pts = [tuple(b), tuple(a)] if i in self.rev else [tuple(a), tuple(b)]
            self.addLines(doc, pts)


def _plate_cases():
    named = {
        "HoleByWidth": dict(hx=10),
        "HoleByWidthUp": dict(hy=10),
        "HoleByWidthLeft": dict(hx=-10),
        "HoleDiagonal": dict(hx=10, hy=10),
        "HoleByWidthCutHole": dict(hx=10, hcut=1),
        "HoleByWidthCutOuter": dict(hx=10, ocut=2),
        "HoleCutOnly": dict(hcut=2),
        "HoleCutOuterCut": dict(hcut=0, ocut=1),
        "OuterCutOnly": dict(ocut=3),
        "PlateByWidth": dict(dx=40),
        "PlateByWidthCut": dict(dx=40, ocut=2),
        "PlateByWidthHoleCut": dict(dx=40, hcut=1),
        "PlateByWidthHoleSlid": dict(dx=40, hx=10, hcut=3),
        "PlateShifted": dict(dx=20, dy=5, ocut=1, hcut=0),
        "HoleCWByWidthCut": dict(hx=10, hcut=1, holeCW=True),
        "HoleCWCut": dict(hcut=2, holeCW=True),
    }
    for nm, kw in named.items():
        name = "ReviewPlate" + nm
        globals()[name] = type(name, (Plate,), dict(kw, __module__=__name__))


_plate_cases()


def _plate_random():
    seed = int(os.environ.get("R5S_SEED", "0"))
    total = int(os.environ.get("R5S_COUNT", "0"))
    if not seed:
        return
    import random as _r

    rng = _r.Random(seed)
    seen = set()
    count = 0
    while count < total:
        hx, hy = rng.choice([(0, 0), (10, 0), (0, 10), (-10, 0), (10, 10), (5, 0), (0, -10)])
        dx, dy = rng.choice([(0, 0), (0, 0), (40, 0), (20, 5), (0, 40)])
        ocut = rng.choice([None, None, 0, 1, 2, 3])
        hcut = rng.choice([None, None, 0, 1, 2, 3])
        cw = rng.random() < 0.4
        if not (hx or hy or dx or dy or ocut is not None or hcut is not None):
            continue
        keep = tuple(sorted(rng.sample(range(8), rng.randint(2, 8))))
        flip = tuple(sorted(i for i in keep if rng.random() < 0.3))
        gone = [i for i in range(8) if i not in keep]
        if ocut is not None:
            gone.append(8)
        if hcut is not None:
            gone.append(9)
        order = tuple(rng.sample(gone, len(gone)))
        rev = tuple(sorted(i for i in gone if rng.random() < 0.4))
        key = (hx, hy, dx, dy, ocut, hcut, cw, keep, flip, order, rev)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        name = "ReviewPlateR%d_%03d_h%s_%s_d%s_%s_o%s_c%s_cw%d_k%s_f%s_ord%s_r%s" % (
            seed,
            count,
            str(hx).replace("-", "m"),
            str(hy).replace("-", "m"),
            str(dx).replace("-", "m"),
            str(dy).replace("-", "m"),
            "N" if ocut is None else ocut,
            "N" if hcut is None else hcut,
            int(cw),
            "".join(map(str, keep)),
            "".join(map(str, flip)) or "N",
            "".join(map(str, order)) or "N",
            "".join(map(str, rev)) or "N",
        )
        globals()[name] = type(
            name,
            (Plate,),
            dict(
                hx=hx, hy=hy, dx=dx, dy=dy, ocut=ocut, hcut=hcut, holeCW=cw, keep=keep,
                flip=flip, order=order, rev=rev, __module__=__name__,
            ),
        )


_plate_random()


# ======================================================================================
# a chamfer moved to another corner, with kept / redrawn / reversed lines in any order
# ======================================================================================
OLDCH = [(0, 0), (20, 0), (20, 15), (15, 20), (0, 20)]  # F R C B L: ids 0-4


class CutMoved(Review):
    abstract = True
    AXES = ("M8", "E5", "E1", "E2")
    newcut = 3  # the square line after which the corner is cut: 0 (20,0), 2 (0,20), 3 (0,0)
    keep = (0, 1, 2, 3, 4)
    flip = ()
    order = ()
    rev = ()
    held = (0, 1, 3, 4)  # old ids with a circle

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in OLDCH])

    def oldLines(self):
        return polyLines(OLDCH)

    def newLines(self):
        lines, cutLine = outLines([[0, 0], [20, 0], [20, 20], [0, 20]], 0, 0, self.newcut, 5)
        return {0: lines[0], 1: lines[1], 3: lines[2], 4: lines[3], 2: cutLine}

    def before(self):
        ls = self.oldLines()
        return [("ends", self.s(*ls[i][0]), self.s(*ls[i][1])) for i in self.held]

    def afterEdit(self):
        ls = self.newLines()
        return [("ends", self.s(*ls[i][0]), self.s(*ls[i][1])) for i in self.held]

    def edit(self, doc):
        ls = self.newLines()
        gone = [i for i in range(5) if i not in self.keep]
        doc.Profile.delGeometries(gone)
        kept = {i: k for k, i in enumerate(self.keep)}
        moves = {}
        for i in self.keep:
            a, b = ls[i]
            moves[kept[i]] = (tuple(b), tuple(a)) if i in self.flip else (tuple(a), tuple(b))
        self.moveLines(doc, moves)
        for i in self.order:
            a, b = ls[i]
            pts = [tuple(b), tuple(a)] if i in self.rev else [tuple(a), tuple(b)]
            self.addLines(doc, pts)


def _cutmoved():
    seed = int(os.environ.get("R5S_SEED", "0"))
    total = int(os.environ.get("R5S_COUNT", "0"))
    if not seed:
        return
    import random as _r

    rng = _r.Random(seed * 7 + 1)
    seen = set()
    count = 0
    while count < total:
        newcut = rng.choice([0, 2, 3, 3])
        keep = tuple(sorted(rng.sample(range(5), rng.randint(1, 5))))
        flip = tuple(sorted(i for i in keep if rng.random() < 0.35))
        gone = [i for i in range(5) if i not in keep]
        order = tuple(rng.sample(gone, len(gone)))
        rev = tuple(sorted(i for i in gone if rng.random() < 0.4))
        held = tuple(sorted(rng.sample([0, 1, 3, 4], rng.randint(1, 4))))
        key = (newcut, keep, flip, order, rev, held)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        name = "ReviewCutMoved%d_%03d_c%d_k%s_f%s_o%s_r%s_h%s" % (
            seed, count, newcut, "".join(map(str, keep)), "".join(map(str, flip)) or "N",
            "".join(map(str, order)) or "N", "".join(map(str, rev)) or "N", "".join(map(str, held)),
        )
        globals()[name] = type(
            name, (CutMoved,),
            dict(newcut=newcut, keep=keep, flip=flip, order=order, rev=rev, held=held, __module__=__name__),
        )


_cutmoved()


# ======================================================================================
# every line of the loop moved (no place vote anywhere), a corner cut in the same edit
# ======================================================================================
class MovedResizedCut(Review):
    """The 20 x 20 square becomes a (w x h) rectangle at (ox, oy) with a corner cut (the square
    line after which the corner is cut: `cut`); all four lines keep their IDs (moved), the cut is a
    new line; a circle on each of the `held` lines. Every circle stays on its own line."""

    abstract = True
    AXES = ("M8", "E5", "E1")
    ox, oy, w, h = 3, 2, 26, 24
    cut = 2
    held = (0, 1, 2, 3)
    size = 4

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in SQUARE])

    def newSquare(self):
        return [[self.ox, self.oy], [self.ox + self.w, self.oy], [self.ox + self.w, self.oy + self.h], [self.ox, self.oy + self.h]]

    def before(self):
        return [("ends", self.s(*SQUARE_LINES[i][0]), self.s(*SQUARE_LINES[i][1])) for i in self.held]

    def afterEdit(self):
        lines, _ = outLines(self.newSquare(), 0, 0, self.cut, self.size)
        return [("ends", self.s(*lines[i][0]), self.s(*lines[i][1])) for i in self.held]

    def edit(self, doc):
        lines, cutLine = outLines(self.newSquare(), 0, 0, self.cut, self.size)
        self.moveLines(doc, {i: (tuple(lines[i][0]), tuple(lines[i][1])) for i in range(4)})
        self.addLines(doc, [tuple(cutLine[0]), tuple(cutLine[1])])


class ReviewSquareMovedResizedCut(MovedResizedCut):
    pass


class ReviewSquareMovedResizedCutHeldFront(MovedResizedCut):
    held = (0,)


class ReviewSquareMovedResizedCutHeldFar(MovedResizedCut):
    """The cut at the back-right corner; the circle on the front line, far from it."""

    held = (0, 3)


class ReviewSquareMovedResizedCut60(MovedResizedCut):
    SCALE = 3.0


class ReviewSquareMovedResizedCut4m(MovedResizedCut):
    SCALE = 200.0


class ReviewSquareMovedOnlyCut(MovedResizedCut):
    """Control: moved by (3, 2), same size (a pure translation): the common move keeps all."""

    w, h = 20, 20


# ======================================================================================
# decision 163's F3: a balanced arc (one cut deleted, the left line redrawn, a new cut)
# ======================================================================================
def _f3():
    import itertools

    for newcut in (3, 0, 2):
        for order in ((2, 4), (4, 2)):
            for rev in ((), (2,), (4,), (2, 4)):
                for keepflip in ((), (1, 3)):
                    name = "ReviewF3Balanced_c%d_o%s_r%s_f%s" % (
                        newcut, "".join(map(str, order)), "".join(map(str, rev)) or "N", "".join(map(str, keepflip)) or "N")
                    globals()[name] = type(
                        name, (CutMoved,),
                        dict(newcut=newcut, keep=(0, 1, 3), flip=keepflip, order=order, rev=rev,
                             held=(0, 1, 3, 4), __module__=__name__),
                    )


_f3()


# ======================================================================================
# thin walls, and a row of square holes slid by its pitch (look-alike places, lines)
# ======================================================================================
class ThinPlate(Plate):
    abstract = True
    HOLE = [(1, 15), (11, 15), (11, 25), (1, 25)]  # 1 from the left wall


class ReviewThinPlateHoleByWidth(ThinPlate):
    hx = 10


class ReviewThinPlateHoleCut(ThinPlate):
    hcut = 1


class ReviewThinPlateHoleByWidthCutOuter(ThinPlate):
    hx = 10
    ocut = 3


class ReviewThinPlateHoleLeftAndCut(ThinPlate):
    """Slid left into the wall's far side? no: 0.5 left, with a cut: the wall thins to 0.5."""

    hx = -0.5
    hcut = 0


class HoleRow(Review):
    """A 90 x 40 plate with three square holes (10 wide at x = 10, 30, 50, y 15..25; pitch 20),
    lines 0-3 the outer, 4-7, 8-11, 12-15 the holes; a circle on every line. The edit slides the
    holes by `slide` in x, every ID kept."""

    abstract = True
    AXES = ("M8", "E5", "E2")
    SIZE = 90
    slide = 20
    cutHole = None

    def holes(self, dx):
        return [[(x + dx, 15), (x + 10 + dx, 15), (x + 10 + dx, 25), (x + dx, 25)] for x in (10, 30, 50)]

    def outer(self):
        return [(0, 0), (90, 0), (90, 40), (0, 40)]

    def allLines(self, dx):
        ls = polyLines(self.outer())
        for h in self.holes(dx):
            ls += polyLines(h)
        return ls

    def profileGeometry(self):
        geos = m.polygon([self.s(*p) for p in self.outer()])
        for h in self.holes(0):
            geos += m.polygon([self.s(*p) for p in h])
        return geos

    def before(self):
        return [("ends", self.s(*a), self.s(*b)) for a, b in self.allLines(0)]

    def afterEdit(self):
        return [("ends", self.s(*a), self.s(*b)) for a, b in self.allLines(self.slide)[:4]] + [
            ("ends", self.s(*a), self.s(*b)) for a, b in self.allLines(self.slide)[4:]
        ]

    def edit(self, doc):
        ls = self.allLines(self.slide)
        self.moveLines(doc, {i: (tuple(a), tuple(b)) for i, (a, b) in enumerate(ls) if i >= 4})


class ReviewHoleRowSlidByPitch(HoleRow):
    slide = 20


class ReviewHoleRowSlidByHalfPitch(HoleRow):
    slide = 10


class ReviewHoleRowSlidByWidth(HoleRow):
    slide = 10
