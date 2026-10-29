# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r5 (class E, E1; ops#264 e2): a random sweep aimed at round 5's three changes to
`pairGeometries`: holes oriented clockwise (the face on the left of every loop), the
emptied-and-filled batch check that now needs a placeless pick, and decision 167's name-only
drop with its common-translation exception (balanced arcs included).

Model: a profile of one or more closed polygons (an outer one and holes), optionally with one
corner cut (`cut0`), padded 10 high; a sketch at z = 0 projects the pad's top face and holds a
circle r 1 by PointOnObject on every side line. The edit moves the whole profile by (dx, dy), puts
the cut at corner `cut1` (or none), keeps the geometries in `keep` (moved to their new place; a
kept old cut line moves to the new cut), deletes the rest and draws the missing lines in `order`
(each reversed if in `rev`). Expected: each circle on the new copy of its own side line (the cut
lines carry none), or the sketch breaks."""

import math
import os
import random

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

SHAPES = {
    "Sq": [[(0, 0), (20, 0), (20, 20), (0, 20)]],
    "L": [[(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)]],
    "U": [[(0, 0), (30, 0), (30, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)]],
    "SqH": [[(0, 0), (30, 0), (30, 30), (0, 30)], [(10, 10), (20, 10), (20, 20), (10, 20)]],
    "SqHcw": [[(0, 0), (30, 0), (30, 30), (0, 30)], [(10, 10), (10, 20), (20, 20), (20, 10)]],
    "RH2": [[(0, 0), (40, 0), (40, 20), (0, 20)],
            [(5, 5), (15, 5), (15, 15), (5, 15)], [(25, 5), (35, 5), (35, 15), (25, 15)]],
}


def matches(g, spec):
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius"):
        return False
    s, e = g.StartPoint, g.EndPoint
    a, b = V(*spec[1], 0), V(*spec[2], 0)
    return (s.isEqual(a, TOL) and e.isEqual(b, TOL)) or (s.isEqual(b, TOL) and e.isEqual(a, TOL))


class HeldBy(Outcome):
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
            if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
                return False, f"circle centre at {centre}"
        return True, ""


def profileLines(polys, dx, dy, cut, size=3):
    """The side lines [(a, b)] of every polygon translated, the corner after global line `cut`
    cut by `size`; and the cut line or None."""
    lines = []
    owner = []
    for p, poly in enumerate(polys):
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            lines.append([[a[0] + dx, a[1] + dy], [b[0] + dx, b[1] + dy]])
            owner.append((p, len(lines) - 1 - i, n))
    cutLine = None
    if cut is not None:
        p, first, n = owner[cut]
        nxt = first + (cut - first + 1) % n
        a, b = lines[cut]
        c, d = lines[nxt]
        ub = (b[0] - a[0], b[1] - a[1])
        k = math.hypot(*ub)
        newEnd = [b[0] - size * ub[0] / k, b[1] - size * ub[1] / k]
        uc = (d[0] - c[0], d[1] - c[1])
        k = math.hypot(*uc)
        newStart = [c[0] + size * uc[0] / k, c[1] + size * uc[1] / k]
        lines[cut][1] = newEnd
        lines[nxt][0] = newStart
        cutLine = [newEnd, newStart]
    return lines, cutLine


class Sweep(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5"
    TIER = "F"
    AXES = ("M8", "E5", "E2")
    REFS = ("circles_on_geometry",)
    shape = "Sq"
    dx = dy = 0
    cut0 = cut1 = None
    keep = flip = order = rev = ()

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def nSides(self):
        return sum(len(p) for p in SHAPES[self.shape])

    def before(self):
        lines, _ = profileLines(SHAPES[self.shape], 0, 0, self.cut0)
        return [("ends", tuple(a), tuple(b)) for a, b in lines]

    def afterEdit(self):
        lines, _ = profileLines(SHAPES[self.shape], self.dx, self.dy, self.cut1)
        return [("ends", tuple(a), tuple(b)) for a, b in lines]

    def build(self, doc):
        body = m.body(doc)
        lines, cutLine = profileLines(SHAPES[self.shape], 0, 0, self.cut0)
        geo = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in lines]
        if cutLine:
            geo.append(Part.LineSegment(V(*cutLine[0], 0), V(*cutLine[1], 0)))
        profile = m.sketch(doc, "Profile", geo, body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        for spec in self.before():
            found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matches(g, spec)]
            if not found:
                raise AssertionError(f"no projected geometry matches {spec}")
            x = (spec[1][0] + spec[2][0]) / 2
            y = (spec[1][1] + spec[2][1]) / 2
            circle = sketch.addGeometry(m.circle(x, y, 1), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, found[0]))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldBy(self.before, self.afterEdit))

    def edit(self, doc):
        n = self.nSides()
        lines, cutLine = profileLines(SHAPES[self.shape], self.dx, self.dy, self.cut1)
        new = lambda i: lines[i] if i < n else cutLine
        total = n + (1 if self.cut0 is not None else 0)
        gone = [i for i in range(total) if i not in self.keep]
        sk = doc.Profile
        if gone:
            sk.delGeometries(gone)
        geometry = sk.Geometry
        for k, i in enumerate(self.keep):
            a, b = new(i)
            if i in self.flip:
                a, b = b, a
            line = geometry[k]
            line.StartPoint = V(-777, -777, 0)
            line.EndPoint = V(*b, 0)
            line.StartPoint = V(*a, 0)
        sk.Geometry = geometry
        for i in self.order:
            a, b = new(i)
            if i in self.rev:
                a, b = b, a
            sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)), False)


RIGHT_TO_LOUD = [
    "ReviewR5S101_035_SqHcw_dx7_dy3_c7_7_k014c_fc_o62753_r237",
    "ReviewR5S101_243_L_dx0_dy0_c5_N_k0_fN_o42135_r5",
    "ReviewR5S101_272_L_dx10_dy0_cN_N_k025_f5_o314_rN",
    "ReviewR5S202_026_RH2_dx0_dy10_c2_2_k02346911c_f11_o810715_r7",
    "ReviewR5S202_141_Sq_dx40_dy0_cN_N_k13_f3_o20_r2",
    "ReviewR5S303_064_RH2_dx20_dy0_cN_11_k01234567891011_f1591011_oc_rN",
    "ReviewR5S303_098_L_dxm20_dy0_cN_5_k23_fN_o5140c_r4c",
    "ReviewR5S303_124_U_dxm20_dy0_c6_6_k16_fN_o274c530_r457",
    "ReviewR5S303_164_SqHcw_dx30_dy0_cN_N_k02345_f3_o176_r67",
]


def _sweep():
    # without PR384R5_SEEDS: the sweep's keys that are right on integration and loud here
    # (seeds 101, 202 and 303, 300 cases each; review pr384-r5)
    seeds = os.environ.get("PR384R5_SEEDS", "") or "101,202,303"
    total = int(os.environ.get("PR384R5_COUNT", "300"))
    only = os.environ.get("PR384R5_ONLY") or (
        None if os.environ.get("PR384R5_SEEDS") else ",".join(RIGHT_TO_LOUD))
    shapes = os.environ.get("PR384R5_SHAPES", "Sq,L,U,SqH,SqHcw,RH2").split(",")
    shifts = [(0, 0), (0, 0), (20, 5), (30, 0), (-20, 0), (0, 10), (7, 3), (40, 0), (20, 0), (10, 0)]
    for seed in map(int, seeds.split(",")):
        rng = random.Random(seed)
        seen = set()
        count = 0
        while count < total:
            shape = rng.choice(shapes)
            polys = SHAPES[shape]
            n = sum(len(p) for p in polys)
            dx, dy = rng.choice(shifts)
            cut0 = rng.choice([None, None] + list(range(n)))
            cut1 = rng.choice([None, cut0, cut0] + list(range(n)))
            total0 = n + (1 if cut0 is not None else 0)
            candidates = [i for i in range(total0) if i < n or cut1 is not None]
            keep = tuple(sorted(rng.sample(candidates, rng.randint(0, len(candidates)))))
            if rng.random() < 0.35:
                keep = tuple(i for i in candidates)  # all kept: moves and cuts only
            flip = tuple(sorted(i for i in keep if rng.random() < 0.3))
            missing = [i for i in range(n) if i not in keep]
            if cut1 is not None and n not in keep:
                missing.append(n)
            order = tuple(rng.sample(missing, len(missing)))
            rev = tuple(sorted(i for i in missing if rng.random() < 0.4))
            if (dx, dy) == (0, 0) and cut0 == cut1 and not missing and not flip:
                continue
            key = (shape, dx, dy, cut0, cut1, keep, flip, order, rev)
            if key in seen:
                continue
            seen.add(key)
            count += 1
            j = lambda t: "".join(map(lambda x: "c" if x == n else str(x), t)) or "N"
            name = "ReviewR5S%d_%03d_%s_dx%s_dy%s_c%s_%s_k%s_f%s_o%s_r%s" % (
                seed, count, shape, str(dx).replace("-", "m"), str(dy).replace("-", "m"),
                "N" if cut0 is None else cut0, "N" if cut1 is None else cut1,
                j(keep), j(flip), j(order), j(rev))
            if only and name not in only.split(","):
                continue
            globals()[name] = type(name, (Sweep,), {
                "shape": shape, "dx": dx, "dy": dy, "cut0": cut0, "cut1": cut1, "keep": keep,
                "flip": flip, "order": order, "rev": rev, "__module__": __name__,
                "__doc__": "Random sweep case (see the module docstring)."})


_sweep()
