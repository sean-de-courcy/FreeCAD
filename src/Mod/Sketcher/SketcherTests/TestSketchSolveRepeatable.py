# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#940): the same sketch solves to the same bits in every process.
# The solver ordered its unknowns by memory address and took the start of a reduced equality from
# the last address, so one sketch gave different coordinates (in the last bits, and sometimes a
# failed solve) from process to process, and a later feature that is sensitive to 1e-13 built in
# one run and refused in the next. Designed geometry: a rounded rectangle with two rounded slots
# inside it, placed by distances, every element started a few tenths off its place. The expected
# result is the same bits everywhere, and a fully constrained, solved sketch.

import hashlib
import math
import os
import subprocess
import sys
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector

OUT = "FREECAD_CH_TEST_SOLVE_OUT"
CHURN = "FREECAD_CH_TEST_SOLVE_CHURN"
PROCESSES = 3

PATH = "FREECAD_CH_TEST_SOLVE_PATH"

CHILD_SCRIPT = """
import os, sys
sys.path.insert(0, os.environ["{path}"])  # this very module, wherever the parent found it
from SketcherTests.TestSketchSolveRepeatable import churn, solveLine
keep = churn(int(os.environ["{churn}"]))
line = solveLine()
with open(os.environ["{out}"], "w", encoding="utf-8") as fh:
    fh.write(line)
os._exit(0)
""".format(churn=CHURN, out=OUT, path=PATH)


def _rounded(sk, x0, y0, w, h, r, j):
    """Four lines and four tangent arcs, each started off by j; equal radii, a radius, a width
    and a height."""
    g0 = sk.GeometryCount
    c = [(x0 + r, y0 + r), (x0 + w - r, y0 + r), (x0 + w - r, y0 + h - r), (x0 + r, y0 + h - r)]
    lines = [
        ((x0 + r, y0), (x0 + w - r, y0)),
        ((x0 + w, y0 + r), (x0 + w, y0 + h - r)),
        ((x0 + w - r, y0 + h), (x0 + r, y0 + h)),
        ((x0, y0 + h - r), (x0, y0 + r)),
    ]
    for i, (a, b) in enumerate(lines):
        sk.addGeometry(
            Part.LineSegment(V(a[0] + j * (i + 1), a[1] - j, 0), V(b[0] - j, b[1] + j * (i + 2), 0)),
            False,
        )
    spans = [(1.5, 2.0), (0.0, 0.5), (0.5, 1.0), (1.0, 1.5)]
    for i, (cx, cy) in enumerate(c):
        circle = Part.Circle(V(cx + j, cy - j, 0), V(0, 0, 1), r + j)
        sk.addGeometry(Part.ArcOfCircle(circle, spans[i][0] * math.pi, spans[i][1] * math.pi), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Tangent", g0 + i, 2, g0 + 4 + (i + 1) % 4, 1))
        sk.addConstraint(Sketcher.Constraint("Tangent", g0 + 4 + i, 2, g0 + i, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", g0))
    sk.addConstraint(Sketcher.Constraint("Horizontal", g0 + 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", g0 + 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", g0 + 3))
    for i in range(1, 4):
        sk.addConstraint(Sketcher.Constraint("Equal", g0 + 4, g0 + 4 + i))
    sk.addConstraint(Sketcher.Constraint("Radius", g0 + 4, r))
    sk.addConstraint(Sketcher.Constraint("DistanceX", g0 + 3, 1, g0 + 1, 1, w))
    sk.addConstraint(Sketcher.Constraint("DistanceY", g0, 1, g0 + 2, 1, h))
    return g0


def buildSketch(doc):
    sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    a = _rounded(sk, -30.0, -20.0, 60.0, 40.0, 3.175, 0.37)
    b = _rounded(sk, -20.0, -10.0, 6.35 * 3, 6.35, 3.175 / 2, 0.21)
    c = _rounded(sk, -20.0, 3.0, 6.35 * 3, 6.35, 3.175 / 2, 0.29)
    sk.addConstraint(Sketcher.Constraint("DistanceX", a + 3, 1, -1, 1, 30.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", a, 1, -1, 1, 20.0))
    sk.addConstraint(Sketcher.Constraint("DistanceX", a + 3, 1, b + 3, 1, 10.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", a, 1, b, 1, 10.0))
    sk.addConstraint(Sketcher.Constraint("DistanceX", b + 3, 1, c + 3, 1, 0.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", b + 2, 1, c, 1, 6.35))
    return sk


def solveLine():
    """Builds the sketch in a new document, recomputes it and returns one line: a hash of the bits
    of every solved coordinate, the sketch's state, solve()'s value and the first coordinate."""
    doc = App.newDocument("SolveRepeatable")
    try:
        sk = buildSketch(doc)
        doc.recompute()
        rows = []
        for g in sk.Geometry:
            for name in ("StartPoint", "EndPoint", "Center"):
                if hasattr(g, name):
                    p = getattr(g, name)
                    rows += [p.x.hex(), p.y.hex()]
        digest = hashlib.sha1(" ".join(rows).encode()).hexdigest()[:12]
        state = "".join(sk.State) or "none"
        return f"{digest} state {state} solve {sk.solve()} numbers {len(rows)} first {rows[0]}"
    finally:
        App.closeDocument(doc.Name)


def churn(n):
    """Leaves n small solved sketches of different sizes alive, so that the parameters of the
    next sketch land elsewhere on the heap. Returns the documents (keep them)."""
    docs = []
    for i in range(n):
        doc = App.newDocument(f"Churn{i}")
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
        for k in range(1 + (7 * i) % 5):
            sk.addGeometry(Part.LineSegment(V(k, i, 0), V(k + 1.5, i + 0.5, 0)), False)
        doc.recompute()
        docs.append(doc)
    return docs


def _freecadCmd():
    packaged = App.ConfigGet("ExeName") + "Cmd"
    names = ((packaged + ".exe", "FreeCADCmd.exe") if sys.platform == "win32" else ("FreeCADCmd", packaged))
    base = os.path.basename(sys.executable).lower()
    if base.startswith("freecadcmd") or base.startswith(packaged.lower()):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(App.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + App.getHomePath())


class TestSketchSolveRepeatable(unittest.TestCase):
    def _check(self, line):
        fields = line.split()
        self.assertEqual(fields[2], "Up-to-date", f"the sketch did not solve cleanly: {line}")
        self.assertEqual(fields[4], "0", f"the sketch did not solve cleanly: {line}")

    def testSameBitsInSeveralProcesses(self):
        """PROCESSES FreeCADCmd processes, each with a different heap before it builds the sketch,
        solve it to the same bits."""
        work = tempfile.mkdtemp(prefix="solve-repeatable-")
        script = os.path.join(work, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(CHILD_SCRIPT)
        procs = []
        for i in range(PROCESSES):
            env = dict(os.environ)
            env[OUT] = os.path.join(work, f"line{i}.txt")
            env[CHURN] = str(3 * i)
            env[PATH] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log = open(os.path.join(work, f"child{i}.log"), "w", encoding="utf-8")
            procs.append(
                (subprocess.Popen([_freecadCmd(), script], env=env, cwd=work, stdout=log,
                                  stderr=subprocess.STDOUT), log, env[OUT])
            )
        lines = []
        for proc, log, out in procs:
            try:
                proc.wait(timeout=600)
            finally:
                log.close()
            self.assertTrue(os.path.isfile(out), f"a child wrote no line ({work})")
            with open(out, encoding="utf-8") as fh:
                lines.append(fh.read().strip())
        # R4: CI's Windows and macOS logs both show this line; it should be the same on both.
        print(f"\nops#940 solve line ({sys.platform}): {lines[0]}")
        for line in lines:
            self._check(line)
        self.assertEqual(len(set(lines)), 1, "different solutions:\n" + "\n".join(lines))

    def testSameBitsInOneProcess(self):
        """The same sketch, built again in this process after other sketches have changed the heap,
        solves to the same bits."""
        first = solveLine()
        keep = churn(4)
        second = solveLine()
        for doc in keep:
            App.closeDocument(doc.Name)
        self._check(first)
        self.assertEqual(first, second)
