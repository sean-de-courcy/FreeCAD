# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r4vs (class E, E1; ops#264 e2): attacks on a face link's pairing aimed at round 5's
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
    FOUND_BY = "review pr384-r4vs"
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


# ---- a chamfer moved to another corner (the batch check's emptied-and-filled test) -------------

CHAMFERED = [(0, 0), (20, 0), (20, 15), (15, 20), (0, 20)]


class ChamferMoved(Review):
    """The 20 x 20 square with its back-right corner cut 5 x 5 (lines F, R, C, B, L, geometry
    IDs 0-4). In one edit the chamfer line is deleted, the corner restored (R and B reach (20, 20))
    and the front-left corner cut instead (F and L shortened, a new chamfer line drawn). `held`
    lists the lines carrying a circle each; every one stays on its own line's new place."""

    abstract = True
    AXES = ("M8", "E5", "E1")
    held = ()
    redrawCut = True  # False: the old chamfer line is kept and moved to the new corner

    OLD = {
        "F": ("y", 0, (0, 20)),
        "R": ("x", 20, (0, 15)),
        "B": ("y", 20, (0, 15)),
        "L": ("x", 0, (0, 20)),
    }
    NEW = {
        "F": ("y", 0, (5, 20)),
        "R": ("x", 20, (0, 20)),
        "B": ("y", 20, (0, 20)),
        "L": ("x", 0, (5, 20)),
    }

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in CHAMFERED])

    def _spec(self, table, key):
        axis, value, (lo, hi) = table[key]
        return (axis, self.s(value), self.s(lo, hi))

    def before(self):
        return [self._spec(self.OLD, k) for k in self.held]

    def afterEdit(self):
        return [self._spec(self.NEW, k) for k in self.held]

    def edit(self, doc):
        # ids: 0 F, 1 R, 2 C, 3 B, 4 L
        self.moveLines(
            doc,
            {
                0: ((5, 0), (20, 0)),
                1: ((20, 0), (20, 20)),
                3: ((20, 20), (0, 20)),
                4: ((0, 20), (0, 5)),
            },
        )
        if self.redrawCut:
            doc.Profile.delGeometries([2])
            self.addLines(doc, [(0, 5), (5, 0)])
        else:
            self.moveLines(doc, {2: ((0, 5), (5, 0))})


class ReviewChamferMovedFRL(ChamferMoved):
    held = ("F", "R", "L")


class ReviewChamferMovedFRBL(ChamferMoved):
    held = ("F", "R", "B", "L")


class ReviewChamferMovedFR(ChamferMoved):
    held = ("F", "R")


class ReviewChamferMovedRL(ChamferMoved):
    held = ("R", "L")


class ReviewChamferMovedKeptFRL(ChamferMoved):
    held = ("F", "R", "L")
    redrawCut = False


class ReviewChamferMovedFRLNoSource(ChamferMoved):
    """The same with the geometry saved before E1 (no source names)."""

    held = ("F", "R", "L")

    def edit(self, doc):
        self.doc = doc = reopenWithoutSources(self, doc)
        super().edit(doc)

    def cleanup(self):
        import shutil

        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


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


class Composed(Review):
    """A profile (`shape`), a circle on each of its lines. The edit moves the whole profile by
    (dx, dy), optionally cutting the corner after line `cut`; the lines in `keep` keep their IDs
    (moved; `flip` swaps the ends of the ones listed), the others are deleted and drawn again in
    `order`, each in the direction `rev` says (the cut line is index n). Each circle must be on
    the translated copy of its own line, or the sketch breaks."""

    abstract = True
    AXES = ("M8", "E5", "E2")
    shape = "Sq"
    notch = 0
    dx = 0
    dy = 0
    cut = None
    keep = ()
    flip = ()
    order = ()
    rev = ()

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in SHAPES[self.shape]])

    def before(self):
        pts = SHAPES[self.shape]
        n = len(pts)
        return [("ends", self.s(*pts[i]), self.s(*pts[(i + 1) % n])) for i in range(n)]

    def newPoints(self):
        """The edited profile's vertices (the base translated; `notch` moves vertices 3..6 in x)."""
        pts = [list(p) for p in SHAPES[self.shape]]
        if self.notch:
            for i in (3, 4, 5, 6):
                pts[i][0] += self.notch
        return pts

    def afterEdit(self):
        lines, _ = outLines(self.newPoints(), self.dx, self.dy, self.cut)
        return [("ends", self.s(*a), self.s(*b)) for a, b in lines]

    def edit(self, doc):
        n = len(SHAPES[self.shape])
        lines, cutLine = outLines(self.newPoints(), self.dx, self.dy, self.cut)
        gone = [i for i in range(n) if i not in self.keep]
        doc.Profile.delGeometries(gone)
        kept = {i: k for k, i in enumerate(self.keep)}
        moves = {}
        for i in self.keep:
            a, b = lines[i]
            moves[kept[i]] = (tuple(b), tuple(a)) if i in self.flip else (tuple(a), tuple(b))
        self.moveLines(doc, moves)
        for i in self.order:
            a, b = lines[i] if i < n else cutLine
            pts = [tuple(b), tuple(a)] if i in self.rev else [tuple(a), tuple(b)]
            self.addLines(doc, pts)


def _compose():
    import os

    seed = int(os.environ.get("PR384_SEED", "20261028"))
    total = int(os.environ.get("PR384_COUNT", "260"))
    rng = random.Random(seed)
    seen = set()
    count = 0
    shifts = {
        "Sq": [(20, 0), (-20, 0), (0, 20), (10, 0), (20, 5), (0, 0), (40, 0)],
        "L": [(30, 0), (10, 0), (0, 10), (-10, 0), (0, 0), (30, 10), (20, 0)],
        "U": [(30, 0), (10, 0), (0, 20), (0, 0), (-10, 0), (20, 0)],
        "N": [(0, 0)],
    }
    notches = [10, -10, 20, 15, 5, -5, 25]
    while count < total:
        shape = rng.choice(["Sq", "Sq", "L", "U", "N", "N", "N"])
        n = len(SHAPES[shape])
        dx, dy = rng.choice(shifts[shape])
        notch = rng.choice(notches) if shape == "N" else 0
        cut = rng.choice([None, None] + list(range(n)))
        keep = tuple(sorted(rng.sample(range(n), rng.randint(0, n))))
        flip = tuple(sorted(i for i in keep if rng.random() < 0.4))
        gone = [i for i in range(n) if i not in keep]
        if cut is not None:
            gone = gone + [n]
        order = tuple(rng.sample(gone, len(gone)))
        rev = tuple(sorted(i for i in gone if rng.random() < 0.4))
        if cut is None and not (dx or dy or notch):
            continue
        key = (shape, notch, dx, dy, cut, keep, flip, order, rev)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        name = "ReviewComposed%s%03d_%s%s_dx%s_dy%s_cut%s_keep%s_flip%s_ord%s_rev%s" % (
            "" if seed == 20261028 else "S%d_" % seed,
            count,
            shape,
            "n%s" % str(notch).replace("-", "m") if notch else "",
            str(dx).replace("-", "m"),
            str(dy).replace("-", "m"),
            "N" if cut is None else cut,
            "".join(map(str, keep)) or "N",
            "".join(map(str, flip)) or "N",
            "".join(map(str, order)) or "N",
            "".join(map(str, rev)) or "N",
        )
        only = os.environ.get("PR384_ONLY")
        if only and name not in only.split(","):
            continue
        globals()[name] = type(
            name,
            (Composed,),
            {
                "shape": shape, "notch": notch, "dx": dx, "dy": dy, "cut": cut, "keep": keep, "flip": flip,
                "order": order, "rev": rev, "__module__": __name__,
            },
        )


# _compose() builds the review's random sweep (debt: wrong on both builds); the corpus keeps
# the explicit cases only (fork PR 384, round 4v)


class ReviewCutRedrawnTranslatedLeft(Composed):
    """The square moved (20, 5) with three lines kept (the right and back ones flipped), the left
    line deleted and drawn again, and the front-left corner cut by a new line drawn after it: the
    sketch gives the new cut line the deleted left line's ID (its end is the front line's start
    cluster), so the circle on the left line lands on the cut line."""

    shape = "Sq"
    dx, dy, cut = 20, 5, 3
    keep, flip, order, rev = (0, 1, 2), (1, 2), (3, 4), (4,)


class ReviewCutRedrawnTranslatedLeftNoFlip(Composed):
    shape = "Sq"
    dx, dy, cut = 20, 5, 3
    keep, flip, order, rev = (0, 1, 2), (), (3, 4), (4,)


class ReviewCutRedrawnTranslatedLeftCutFirst(Composed):
    shape = "Sq"
    dx, dy, cut = 20, 5, 3
    keep, flip, order, rev = (0, 1, 2), (1, 2), (4, 3), (4,)


# ---- a pie slice rotated: the same circle's arc with its middle turned (sameSide's midpoint) ------


class Pie(Review):
    """A pie slice: centre O = (0, 0), radius 10, two radii (angles 0 and `sweep` degrees) and the
    arc between them (counter-clockwise). The edit turns the slice about O by `turn` degrees, every
    geometry keeping its ID (the arc stays on the same circle: its middle moves by `turn`),
    optionally cutting the corner at O (one radius shortened, a short line drawn: the list
    changes). A circle on the arc: it must stay on the arc."""

    abstract = True
    AXES = ("M8", "E5", "E2")
    sweep = 200
    turn = 100
    chamfer = False
    R = 10

    def pts(self, a0):
        a1 = a0 + self.sweep
        r = self.s(self.R)
        p0 = (r * math.cos(math.radians(a0)), r * math.sin(math.radians(a0)))
        p1 = (r * math.cos(math.radians(a1)), r * math.sin(math.radians(a1)))
        return p0, p1

    def geometry(self, a0, chamfer=False):
        a1 = a0 + self.sweep
        p0, p1 = self.pts(a0)
        r = self.s(self.R)
        arc = Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), r),
                               math.radians(a0), math.radians(a1))
        c = self.s(2.0) / self.s(self.R)
        if chamfer:
            q0 = (p0[0] * c, p0[1] * c)
            q1 = (p1[0] * c, p1[1] * c)
            return [Part.LineSegment(V(*q0, 0), V(*p0, 0)), arc,
                    Part.LineSegment(V(*p1, 0), V(*q1, 0)), Part.LineSegment(V(*q1, 0), V(*q0, 0))]
        return [Part.LineSegment(V(0, 0, 0), V(*p0, 0)), arc, Part.LineSegment(V(*p1, 0), V(0, 0, 0))]

    def profileGeometry(self):
        return self.geometry(0)

    def before(self):
        return [("arc", (0, 0), self.s(self.R))]

    def afterEdit(self):
        return [("arc", (0, 0), self.s(self.R))]

    def edit(self, doc):
        # the profile sketch is turned through its Placement: every geometry keeps its ID
        sk = doc.Profile
        if self.chamfer:
            g = self.geometry(0, True)
            m.setLines(sk, {
                0: ((g[0].StartPoint.x, g[0].StartPoint.y), (g[0].EndPoint.x, g[0].EndPoint.y)),
                2: ((g[2].StartPoint.x, g[2].StartPoint.y), (g[2].EndPoint.x, g[2].EndPoint.y)),
            })
            sk.addGeometry(g[3], False)
        sk.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), self.turn))


class ReviewPieTurned100(Pie):
    turn = 100


class ReviewPieTurned100Chamfer(Pie):
    turn = 100
    chamfer = True


class ReviewPieTurned30Chamfer(Pie):
    turn = 30
    chamfer = True


class ReviewPieTurned100ChamferNoSource(ReviewPieTurned100Chamfer):
    def edit(self, doc):
        self.doc = doc = reopenWithoutSources(self, doc)
        super().edit(doc)

    def cleanup(self):
        import shutil

        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class ReviewPieTurned100NoSource(ReviewPieTurned100ChamferNoSource):
    chamfer = False


class ReviewPieTurned30ChamferNoSource(ReviewPieTurned100ChamferNoSource):
    turn = 30


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
