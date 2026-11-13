# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 item 8, perf: scaling tests)

"""Scaling: how the time of one recompute grows with the size of its input. Each family builds a
designed model at three sizes N, times one stage (CPU time, the best of a few repeats, so other
load on the machine counts little), and fits the slope of log time against log N by least squares.
A slope of 1 is linear; a family fails above LIMIT (1.3). The families:

- sketch: N fully constrained slots in one sketch (the solve and the sketch's shape);
- prism_faces: one Pad of N squares up to the underside of a ceiling plate;
- history: one more Pad up to that face on a body that already has N of them (the cost of one
  feature against the size of its body; the sum over a whole history is one power higher);
- wave: a closed wavy outline of N tangent arcs, its whole top rim rounded (one tangent chain);
- star: a star of N teeth, its 2N top edges rounded (N convex and N reflex mitres);
- split_chamfer: a plate cut by one Pocket of N grooves, then the 2N groove rims chamfered;
- pattern: a linear pattern of N occurrences of a small boss;
- edge_picks: a Fillet naming N edges, one per boss on a plate of N bosses (the link assignment
  and the recompute).

Every stage checks its result against a volume defined by the geometry, so a fast wrong answer
can't pass. A family whose slope is above the limit on the build this file was written on is an
expected failure, listed in EXPECTED_SLOW with the slope measured there at N = 50 to 400 (ops#640
and ops#675, x204e, 2026-11-13): when it is fixed, its unexpected success says so, and its entry
goes. The sizes here are small, for CI; a small N understates a slope (constant costs), so a
family passing here may still be superlinear at ten times the size."""

import math
import time
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector

LIMIT = 1.3

# family -> (sizes, repeats)
SIZES = {
    # Above 40 slots: from 15 to 35 the solve takes another path, 0.4 s at 15 to 11 s at 35, then
    # 1.7 s at 40 (b14l)
    "sketch": ((40, 60, 80), 2),
    "prism_faces": ((25, 50, 100), 2),
    "history": ((12, 25, 50), 3),
    "wave": ((50, 100, 200), 2),
    "star": ((25, 50, 100), 2),
    "split_chamfer": ((12, 25, 50), 2),
    "pattern": ((100, 200, 400), 2),
    "edge_picks": ((25, 50, 100), 2),
}

# family -> the slope on feat/onshape-experiment-b14l 49d7471b10 (Linux, CPU time, N = 50 to 400)
EXPECTED_SLOW = {
    "sketch": 3.14,  # 2.4 / 22 / 186 s at 50 / 100 / 200 slots; the solve alone 3.05
    "wave": 1.67,
    "star": 1.97,  # at 400 it stops at the 60 s GeometryTimeLimit
    "split_chamfer": 2.04,
    "edge_picks": 1.71,  # the link assignment alone is 1.98
}

# Families whose stage is repeated on one document (the setup is the costly part)
SAME_DOCUMENT = {"history"}


def rect(sk, x0, y0, x1, y1):
    g = sk.addGeometry(
        [
            Part.LineSegment(V(x0, y0, 0), V(x1, y0, 0)),
            Part.LineSegment(V(x1, y0, 0), V(x1, y1, 0)),
            Part.LineSegment(V(x1, y1, 0), V(x0, y1, 0)),
            Part.LineSegment(V(x0, y1, 0), V(x0, y0, 0)),
        ]
    )
    sk.addConstraint(
        [Sketcher.Constraint("Coincident", g[0] + i, 2, g[0] + (i + 1) % 4, 1) for i in range(4)]
    )


def grid(n, pitch):
    cols = int(math.ceil(math.sqrt(n)))
    return [((i % cols) * pitch, (i // cols) * pitch) for i in range(n)], cols


def plate(doc, length, width, height, z=0):
    body = doc.addObject("PartDesign::Body", "Body")
    box = body.newObject("PartDesign::AdditiveBox", "Plate")
    box.Length, box.Width, box.Height = length, width, height
    box.Placement = App.Placement(V(0, 0, z), App.Rotation())
    return body, box


def wrongVolume(feature, want, what="volume"):
    """An error text unless the feature is valid and its volume is the wanted one."""
    if not feature.isValid() or feature.Shape.isNull():
        return "%s failed: %s" % (feature.Name, feature.getStatusString())
    if abs(feature.Shape.Volume - want) > 1e-6 * want:
        return "%s %.6f, want %.6f" % (what, feature.Shape.Volume, want)
    return ""


# Each family: (doc, n) -> stage; stage() runs the timed step and returns an error text or "".


def famSketch(doc, n):
    sk = doc.addObject("Sketcher::SketchObject", "Slots")
    pts, _ = grid(n, 10.0)
    cons = []
    r, length = 1.0, 4.0
    for x, y in pts:
        l0, l1, a0, a1 = sk.addGeometry(
            [
                Part.LineSegment(V(x, y - r, 0), V(x + length, y - r, 0)),
                Part.LineSegment(V(x + length, y + r, 0), V(x, y + r, 0)),
                Part.ArcOfCircle(
                    Part.Circle(V(x + length, y, 0), V(0, 0, 1), r), -math.pi / 2, math.pi / 2
                ),
                Part.ArcOfCircle(
                    Part.Circle(V(x, y, 0), V(0, 0, 1), r), math.pi / 2, 3 * math.pi / 2
                ),
            ]
        )
        cons += [
            Sketcher.Constraint("Tangent", l0, 2, a0, 1),
            Sketcher.Constraint("Tangent", a0, 2, l1, 1),
            Sketcher.Constraint("Tangent", l1, 2, a1, 1),
            Sketcher.Constraint("Tangent", a1, 2, l0, 1),
            Sketcher.Constraint("Horizontal", l0),
            Sketcher.Constraint("Equal", a0, a1),
            Sketcher.Constraint("Radius", a0, r),
            Sketcher.Constraint("Distance", l0, length),
            Sketcher.Constraint("DistanceX", -1, 1, a1, 3, x),
            Sketcher.Constraint("DistanceY", -1, 1, a1, 3, y),
        ]
    sk.addConstraint(cons)

    def stage():
        sk.touch()
        doc.recompute()
        # Every slot is one closed wire: two half discs of r and a rectangle 2 r by its length
        wires = sk.Shape.Wires
        area = sum(Part.Face(w).Area for w in wires)
        want = n * (math.pi * r * r + 2 * r * length)
        if len(wires) != n or abs(area - want) > 1e-6 * want:
            return "%d wires of area %.6f, want %d of %.6f" % (len(wires), area, n, want)
        return ""

    return stage


def ceilingPlate(doc, n):
    """A plate from z = 10 to 11 over a grid of n cells of 5, and the name of its underside."""
    pts, cols = grid(n, 5.0)
    side = cols * 5.0 + 5
    body, ceiling = plate(doc, side, side, 1, z=10)
    doc.recompute()
    under = next(
        "Face%d" % i
        for i, f in enumerate(ceiling.Shape.Faces, 1)
        if abs(f.CenterOfMass.z - 10) < 1e-9 and f.Surface.TypeId == "Part::GeomPlane"
    )
    return pts, side, body, ceiling, under


def famPrismFaces(doc, n):
    pts, side, body, ceiling, under = ceilingPlate(doc, n)
    sk = body.newObject("Sketcher::SketchObject", "Squares")
    for x, y in pts:
        rect(sk, x + 1, y + 1, x + 3, y + 3)
    doc.recompute()

    def stage():
        pad = body.newObject("PartDesign::Pad", "Pillars")
        pad.Profile = sk
        pad.Type = "UpToFace"
        pad.UpToFace = (ceiling, [under])
        doc.recompute()
        # The ceiling and n pillars of 2 x 2 x 10
        return wrongVolume(pad, side * side + n * 40.0)

    return stage


def famHistory(doc, n):
    # Room for the n pillars of the setup and the timed ones after them
    pts, side, body, ceiling, under = ceilingPlate(doc, n + 8)
    count = [0]

    def pillar():
        x, y = pts[count[0]]
        sk = body.newObject("Sketcher::SketchObject", "Square%d" % count[0])
        rect(sk, x + 1, y + 1, x + 3, y + 3)
        pad = body.newObject("PartDesign::Pad", "Pillar%d" % count[0])
        pad.Profile = sk
        pad.Type = "UpToFace"
        pad.UpToFace = (ceiling, [under])
        doc.recompute()
        count[0] += 1
        return wrongVolume(pad, side * side + count[0] * 40.0)

    for _ in range(n):
        error = pillar()
        if error:
            raise AssertionError("history setup: " + error)
    return pillar


def roundSection(r):
    """The section a round of r removes at a square edge (a square r x r less a quarter disc):
    its area, and how far its centroid is in from the wall."""
    return r * r * (1 - math.pi / 4), r * (5.0 / 6 - math.pi / 4) / (1 - math.pi / 4)


def polygonRound(pts, r):
    """The volume a round of r removes along the whole top rim of a polygon prism with mitred
    corners: area (L - 2 x_c sum tan(phi_i / 2)), phi_i the signed exterior angles."""
    area, xc = roundSection(r)
    length = tans = 0.0
    for i in range(len(pts)):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        d1, d2 = b - a, c - b
        length += d2.Length
        tans += math.tan(math.atan2(d1.x * d2.y - d1.y * d2.x, d1.x * d2.x + d1.y * d2.y) / 2)
    return area * (length - 2 * xc * tans)


def roundedPrism(doc, geometry, edges, radius, removed):
    """A prism 3 high over the closed outline; the stage rounds its whole top rim."""
    body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Outline")
    sk.addGeometry(geometry)
    pad = body.newObject("PartDesign::Pad", "Prism")
    pad.Profile = sk
    pad.Length = 3.0
    doc.recompute()
    top = [
        "Edge%d" % i
        for i, e in enumerate(pad.Shape.Edges, 1)
        if abs(e.BoundBox.ZMin - 3) < 1e-9 and abs(e.BoundBox.ZMax - 3) < 1e-9
    ]
    volume = pad.Shape.Volume

    def stage():
        if len(top) != edges:
            return "%d top edges, want %d" % (len(top), edges)
        f = body.newObject("PartDesign::Fillet", "Round")
        f.Base = (pad, top)
        f.Radius = radius
        doc.recompute()
        if not f.isValid() or f.Shape.isNull():
            return "the round failed: %s" % f.getStatusString()
        if abs((volume - f.Shape.Volume) - removed) > 1e-4 * removed:
            return "the round removes %.6f, want %.6f" % (volume - f.Shape.Volume, removed)
        return ""

    return stage


def famWave(doc, n):
    # n arcs of radius 1 (n even), centres on a circle, bulging out and in by turns, each tangent
    # to the next. A smooth closed outline of length L loses area (L - 2 pi x_c) (Pappus: the
    # total turning is 2 pi), and L = n pi.
    n += n % 2
    big = 1.0 / math.sin(math.pi / n)
    half = math.pi / 2 + math.pi / n
    arcs = []
    for k in range(n):
        at = 2 * math.pi * k / n
        circle = Part.Circle(V(big * math.cos(at), big * math.sin(at), 0), V(0, 0, 1), 1.0)
        if k % 2 == 0:
            arcs.append(Part.ArcOfCircle(circle, at - half, at + half))
        else:
            arcs.append(Part.ArcOfCircle(circle, at + half, at - half + 2 * math.pi))
    area, xc = roundSection(0.2)
    return roundedPrism(doc, arcs, n, 0.2, area * (n * math.pi - 2 * math.pi * xc))


def famStar(doc, n):
    # Tips on R, notches on R - 1.5, pitch 2 along the tip circle: the same tooth at every n
    big = 2.0 * n / math.pi
    m = 2 * n
    pts = [
        V(
            (big if i % 2 == 0 else big - 1.5) * math.cos(math.pi * i / n),
            (big if i % 2 == 0 else big - 1.5) * math.sin(math.pi * i / n),
            0,
        )
        for i in range(m)
    ]
    sides = [Part.LineSegment(pts[i], pts[(i + 1) % m]) for i in range(m)]
    return roundedPrism(doc, sides, m, 0.2, polygonRound(pts, 0.2))


def famSplitChamfer(doc, n):
    pitch, gw, width, height, depth, size = 4.0, 1.0, 20.0, 3.0, 1.5, 0.2
    length = (n + 1) * pitch
    body, _ = plate(doc, length, width, height)
    doc.recompute()

    def stage():
        sk = body.newObject("Sketcher::SketchObject", "Grooves")
        sk.Placement = App.Placement(V(0, 0, height), App.Rotation())
        for k in range(n):
            x = (k + 1) * pitch - gw / 2
            rect(sk, x, -1, x + gw, width + 1)
        pocket = body.newObject("PartDesign::Pocket", "Cut")
        pocket.Profile = sk
        pocket.Length = depth
        doc.recompute()
        rims = [
            "Edge%d" % i
            for i, e in enumerate(pocket.Shape.Edges, 1)
            if abs(e.BoundBox.ZMin - height) < 1e-9
            and abs(e.BoundBox.ZMax - height) < 1e-9
            and e.BoundBox.XLength < 1e-9
            and 1e-9 < e.BoundBox.XMin < length - 1e-9
        ]
        if len(rims) != 2 * n:
            return "%d groove rims, want %d" % (len(rims), 2 * n)
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pocket, rims)
        chamfer.Size = size
        doc.recompute()
        # The plate less n grooves, less a triangle of size^2 / 2 along each rim
        grooves = n * gw * width * depth
        return wrongVolume(chamfer, length * width * height - grooves - n * width * size * size)

    return stage


def famPattern(doc, n):
    length = 2.0 * n + 2
    body, _ = plate(doc, length, 4, 1)
    sk = body.newObject("Sketcher::SketchObject", "Square")
    sk.Placement = App.Placement(V(0, 0, 1), App.Rotation())
    rect(sk, 0.5, 1.5, 1.5, 2.5)
    pad = body.newObject("PartDesign::Pad", "Boss")
    pad.Profile = sk
    pad.Length = 1
    doc.recompute()

    def stage():
        # Made in the document, then added to the body (as TestLinearPattern does)
        pattern = doc.addObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pad]
        pattern.Direction = (sk, ["H_Axis"])
        pattern.Length = 2.0 * (n - 1)
        pattern.Occurrences = n
        body.addObject(pattern)
        doc.recompute()
        # The plate and n bosses of 1
        return wrongVolume(pattern, length * 4 + n)

    return stage


def famEdgePicks(doc, n):
    pts, cols = grid(n, 3.0)
    side = cols * 3.0 + 3
    body, _ = plate(doc, side, side, 1)
    sk = body.newObject("Sketcher::SketchObject", "Squares")
    sk.Placement = App.Placement(V(0, 0, 1), App.Rotation())
    for x, y in pts:
        rect(sk, x + 1, y + 1, x + 2, y + 2)
    pad = body.newObject("PartDesign::Pad", "Bosses")
    pad.Profile = sk
    pad.Length = 1
    doc.recompute()
    corners = {(round(x + 2, 6), round(y + 2, 6)) for x, y in pts}
    picks = [
        "Edge%d" % i
        for i, e in enumerate(pad.Shape.Edges, 1)
        if e.BoundBox.XLength < 1e-9
        and e.BoundBox.YLength < 1e-9
        and (round(e.BoundBox.XMin, 6), round(e.BoundBox.YMin, 6)) in corners
    ]
    volume = pad.Shape.Volume

    def stage():
        if len(picks) != n:
            return "%d picks, want %d" % (len(picks), n)
        f = body.newObject("PartDesign::Fillet", "Round")
        f.Radius = 0.2
        f.Base = (pad, picks)
        doc.recompute()
        # Each picked edge, 1 long, loses the round's section
        return wrongVolume(f, volume - n * roundSection(0.2)[0])

    return stage


FAMILIES = {
    "sketch": famSketch,
    "prism_faces": famPrismFaces,
    "history": famHistory,
    "wave": famWave,
    "star": famStar,
    "split_chamfer": famSplitChamfer,
    "pattern": famPattern,
    "edge_picks": famEdgePicks,
}


def slope(points):
    """The least squares slope of log t against log n."""
    xs = [math.log(n) for n, _ in points]
    ys = [math.log(max(t, 1e-3)) for _, t in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


def timed(stage, family, n):
    t0 = time.process_time()
    error = stage()
    t = time.process_time() - t0
    if error:
        raise AssertionError("%s at N = %d: %s" % (family, n, error))
    return t


def measure(family, n, repeats):
    """The best CPU time of the family's stage at size n."""
    times = []
    if family in SAME_DOCUMENT:
        doc = App.newDocument("TestScaling")
        doc.UndoMode = 0
        try:
            stage = FAMILIES[family](doc, n)
            times = [timed(stage, family, n) for _ in range(repeats)]
        finally:
            App.closeDocument(doc.Name)
        return min(times)
    for _ in range(repeats):
        doc = App.newDocument("TestScaling")
        doc.UndoMode = 0
        try:
            times.append(timed(FAMILIES[family](doc, n), family, n))
        finally:
            App.closeDocument(doc.Name)
    return min(times)


class TestScaling(unittest.TestCase):
    def check(self, family):
        sizes, repeats = SIZES[family]
        points = [(n, measure(family, n, repeats)) for n in sizes]
        s = slope(points)
        text = "%s: slope %.2f (%s)" % (family, s, ", ".join("N %d: %.3f s" % p for p in points))
        App.Console.PrintMessage("TestScaling " + text + "\n")
        self.assertLessEqual(s, LIMIT, text)


def makeTest(family):
    def test(self):
        self.check(family)

    test.__doc__ = "The %s family grows no faster than N^%.1f." % (family, LIMIT)
    return unittest.expectedFailure(test) if family in EXPECTED_SLOW else test


for _family in FAMILIES:
    setattr(TestScaling, "test_" + _family, makeTest(_family))
