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


OX = OY = 0.0


def combPts(N, shift, k=1.0):
    pts = [(0, 0), (4 * N, 0), (4 * N, 6)]
    for i in range(N - 1, -1, -1):
        pts += [(4 * i + 3 + shift, 6), (4 * i + 3 + shift, 10), (4 * i + 1 + shift, 10), (4 * i + 1 + shift, 6)]
    pts += [(0, 6)]
    return [(x * k + OX, y + OY) for x, y in pts]


class CombTime(Review):
    abstract = True
    SIZE = 400
    N = 70
    shift = 0.5
    kx = 1.0

    def profileGeometry(self):
        return m.polygon(combPts(self.N, 0))

    def lines(self, pts):
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

    def held(self):
        n = len(combPts(self.N, 0))
        return [0, n - 1, 5, 10, n - 8]

    def before(self):
        ls = self.lines(combPts(self.N, 0))
        return [("ends", ls[i][0], ls[i][1]) for i in self.held()]

    def afterEdit(self):
        ls = self.lines(combPts(self.N, self.shift, self.kx))
        n = len(ls)
        out = []
        for i in self.held():
            a, b = ls[i]
            if i == 0:
                a = (3 + OX, OY)
            if i == n - 1:
                b = (OX, 3 + OY)
            out.append(("ends", a, b))
        return out

    def edit(self, doc):
        pts = combPts(self.N, self.shift, self.kx)
        ls = self.lines(pts)
        n = len(ls)
        moves = {}
        for i, (a, b) in enumerate(ls):
            if i == 0:
                a = (3 + OX, OY)
            if i == n - 1:
                b = (OX, 3 + OY)
            moves[i] = (a, b)
        self.moveLines(doc, moves)
        self.addLines(doc, [(OX, 3 + OY), (3 + OX, OY)])


class ReviewCombMovedStretchedCut(CombTime):
    """Every line moved (x * 1.01 and 0.3 up and right) with a corner cut: no line keeps its place."""
    shift = 0.0
    kx = 1.01

    def build(self, doc):
        global OX, OY
        OX = OY = 0.0
        super().build(doc)

    def edit(self, doc):
        global OX, OY
        OX = OY = 0.3
        import time
        super().edit(doc)
        t0 = time.time()
        doc.recompute()
        print("CASETIME", type(self).__name__, "N", self.N, "edges", len(combPts(self.N, 0)), "recompute %.2fs" % (time.time() - t0))

    def afterEdit(self):
        return super().afterEdit()


class ReviewCombMovedStretchedCut200(ReviewCombMovedStretchedCut):
    N = 200


class ReviewCombMovedStretchedCut30(ReviewCombMovedStretchedCut):
    N = 30


class ReviewCombMovedStretchedCut120(ReviewCombMovedStretchedCut):
    N = 120
