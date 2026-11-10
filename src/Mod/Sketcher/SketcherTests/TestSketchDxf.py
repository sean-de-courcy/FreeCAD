# SPDX-License-Identifier: LGPL-2.1-or-later

"""DXF into sketches and out of faces and sketches (FreeCAD-CH, the DXF lane), without the GUI.

Designed geometry only: every file here is written by this module.
- The logo: five closed loops of 3,650 short R12 LINE segments, as logos arrive. A shield whose
  top is a sine wave (corners where it meets the sides and at the bottom tip), a circle, a rounded
  rectangle (four long sides, four flattened corner arcs), a crescent with two sharp tips, and a
  13-point star (26 sharp corners). The truth is the polygon itself: each loop's area is its
  shoelace area, and a fit within tolerance t moves it by at most t times the loop's length.
- Small files for each entity kind: an ARC, a CIRCLE, an LWPOLYLINE with bulges (a slot: two
  half circles), an ELLIPSE, a SPLINE, nested and mirrored INSERTs of a block, a POLYLINE, text.
- A designed plate (a box with a hole, a slot and an elliptical pocket on its top face) for the
  export, read back by the importer: areas and loop counts compared.
"""

import math
import os
import tempfile
import time
import unittest

import FreeCAD
import Part
import Sketcher

import SketcherDxf
from SketcherDxf import reader

V = FreeCAD.Vector


# ---------------------------------------------------------------------------------------------
# designed files


def _poly(f, a, b, n, closed_end=True):
    """n segments of the curve f over [a, b], as points (end included)"""
    return [f(a + (b - a) * k / n) for k in range(n + 1)]


def logo_loops():
    """The logo's five loops, each a closed list of points (first point repeated last)"""
    loops = []
    # 1. shield: top wave from (-30, 20) to (30, 20), right side a cubic to the tip (0, -25),
    # left side back up: corners at both top ends and at the tip
    top = _poly(lambda x: (x, 20.0 + 1.5 * math.sin(2.0 * math.pi * x / 20.0)), -30.0, 30.0, 700)

    def bez(p0, p1, p2, p3):
        def f(t):
            s = 1.0 - t
            return (
                s**3 * p0[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t**3 * p3[0],
                s**3 * p0[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t**3 * p3[1],
            )

        return f

    right = _poly(bez((30.0, 20.0), (32.0, 0.0), (18.0, -18.0), (0.0, -25.0)), 0.0, 1.0, 600)
    left = _poly(bez((0.0, -25.0), (-18.0, -18.0), (-32.0, 0.0), (-30.0, 20.0)), 0.0, 1.0, 600)
    loops.append(top + right[1:] + left[1:])
    # 2. circle r 6 at (-12, 6), 360 segments
    loops.append(_poly(lambda t: (-12.0 + 6.0 * math.cos(t), 6.0 + 6.0 * math.sin(t)), 0.0, 2 * math.pi, 360))
    loops[-1][-1] = loops[-1][0]
    # 3. rounded rectangle 16 x 8 at (12, 6), corner radius 2: 4 long sides, 4 x 40 arc segments
    rr = []
    cx, cy, hw, hh, r = 12.0, 6.0, 8.0, 4.0, 2.0
    for k, (ox, oy) in enumerate(((hw - r, -hh + r), (hw - r, hh - r), (-hw + r, hh - r), (-hw + r, -hh + r))):
        a0 = -math.pi / 2 + k * math.pi / 2
        rr += _poly(lambda t: (cx + ox + r * math.cos(t), cy + oy + r * math.sin(t)), a0, a0 + math.pi / 2, 40)
    rr.append(rr[0])
    loops.append(rr)
    # 4. crescent: upper and lower cosine arches meeting at sharp tips (+-15, -8)
    up = _poly(lambda x: (x, -8.0 + 4.0 * math.cos(math.pi * x / 30.0)), 15.0, -15.0, 600)
    lo = _poly(lambda x: (x, -8.0 - 3.0 * math.cos(math.pi * x / 30.0)), -15.0, 15.0, 600)
    loops.append(up + lo[1:])
    # 5. a 13-point star at (0, 12), radii 3 and 1.5: 26 sharp corners
    st = []
    for k in range(26):
        rad = 3.0 if k % 2 == 0 else 1.5
        a = math.pi / 2 + k * math.pi / 13
        st.append((0.0 + rad * math.cos(a), 12.0 + rad * math.sin(a)))
    st.append(st[0])
    loops.append(st)
    return loops


LOGO_CORNERS = [(-30.0, 20.0), (30.0, 20.0), (0.0, -25.0), (15.0, -8.0), (-15.0, -8.0)]


def shoelace(pts):
    return 0.5 * sum(pts[k][0] * pts[k + 1][1] - pts[k + 1][0] * pts[k][1] for k in range(len(pts) - 1))


def length(pts):
    return sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1))


def dxf_text(entities, insunits=4, blocks=""):
    """An R12-style DXF of the given ENTITIES text (insunits None: no header)"""
    head = ""
    if insunits is not None:
        head = f"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$INSUNITS\n70\n{insunits}\n0\nENDSEC\n"
    if blocks:
        blocks = f"0\nSECTION\n2\nBLOCKS\n{blocks}0\nENDSEC\n"
    return f"{head}{blocks}0\nSECTION\n2\nENTITIES\n{entities}0\nENDSEC\n0\nEOF\n"


def lines_text(loops):
    out = []
    for pts in loops:
        for k in range(len(pts) - 1):
            p, q = pts[k], pts[k + 1]
            out.append(f"0\nLINE\n8\nlogo\n10\n{p[0]!r}\n20\n{p[1]!r}\n30\n0.0\n11\n{q[0]!r}\n21\n{q[1]!r}\n31\n0.0\n")
    return "".join(out)


def write(dirname, name, text):
    path = os.path.join(dirname, name)
    with open(path, "w", encoding="ascii") as f:
        f.write(text)
    return path


def new_sketch(doc, name="Sketch"):
    return doc.addObject("Sketcher::SketchObject", name)


def sketch_faces(sketch):
    """The sketch's closed wires as faces (Bullseye: the holes inside the outer loop)"""
    wires = sketch.Shape.Wires
    return wires, [Part.Face(w) for w in wires]


# ---------------------------------------------------------------------------------------------


class TestDxfReader(unittest.TestCase):
    """Each entity kind lands as the curve it is, in the file's units"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dxf_")
        self.doc = FreeCAD.newDocument("DxfReader")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def insert(self, text, **kw):
        if "SECTION" not in text:
            text = dxf_text(text)
        sk = new_sketch(self.doc)
        rep = SketcherDxf.insert(sk, write(self.dir, "t.dxf", text), **kw)
        self.doc.recompute()
        return sk, rep

    def test_arc_circle_ellipse_spline(self):
        ents = (
            "0\nARC\n8\n0\n10\n1.0\n20\n2.0\n30\n0.0\n40\n3.0\n50\n0.0\n51\n90.0\n"
            "0\nCIRCLE\n8\n0\n10\n10.0\n20\n0.0\n30\n0.0\n40\n2.0\n"
            "0\nELLIPSE\n8\n0\n10\n20.0\n20\n0.0\n30\n0.0\n11\n4.0\n21\n0.0\n31\n0.0\n40\n0.5\n41\n0.0\n42\n6.283185307179586\n"
            "0\nSPLINE\n8\n0\n70\n8\n71\n3\n72\n8\n73\n4\n40\n0\n40\n0\n40\n0\n40\n0\n40\n1\n40\n1\n40\n1\n40\n1\n"
            "10\n0.0\n20\n-5.0\n30\n0.0\n10\n2.0\n20\n-3.0\n30\n0.0\n10\n4.0\n20\n-7.0\n30\n0.0\n10\n6.0\n20\n-5.0\n30\n0.0\n"
        )
        sk, rep = self.insert(ents)
        kinds = [g.TypeId for g in sk.Geometry]
        self.assertEqual(
            kinds,
            ["Part::GeomArcOfCircle", "Part::GeomCircle", "Part::GeomEllipse", "Part::GeomBSplineCurve"],
        )
        arc = sk.Geometry[0]
        self.assertAlmostEqual(arc.Radius, 3.0, 12)
        self.assertTrue((arc.StartPoint - V(4, 2, 0)).Length < 1e-12)
        self.assertTrue((arc.EndPoint - V(1, 5, 0)).Length < 1e-12)
        ell = sk.Geometry[2]
        self.assertAlmostEqual(ell.MajorRadius, 4.0, 12)
        self.assertAlmostEqual(ell.MinorRadius, 2.0, 12)
        self.assertTrue((sk.Geometry[3].EndPoint - V(6, -5, 0)).Length < 1e-12)
        self.assertTrue(rep.units_from_file)
        self.assertEqual(rep.units, "mm")
        # each curve held by one Block, and the sketch solves
        self.assertEqual([c.Type for c in sk.Constraints], ["Block"] * 4)
        self.assertEqual(sk.solve(), 0)

    def test_bulge_slot_and_units(self):
        # a slot 10 x 4 (inches): two lines and two half circles by bulge 1
        ents = (
            "0\nLWPOLYLINE\n8\n0\n90\n4\n70\n1\n"
            "10\n0.0\n20\n0.0\n42\n0.0\n10\n10.0\n20\n0.0\n42\n1.0\n10\n10.0\n20\n4.0\n42\n0.0\n10\n0.0\n20\n4.0\n42\n1.0\n"
        )
        sk, rep = self.insert(dxf_text(ents, insunits=None), units="in")
        self.assertEqual(rep.units, "in")
        self.assertFalse(rep.units_from_file)
        kinds = sorted(g.TypeId for g in sk.Geometry)
        self.assertEqual(kinds, ["Part::GeomArcOfCircle"] * 2 + ["Part::GeomLineSegment"] * 2)
        face = Part.Face(sk.Shape.Wires[0])
        exact = (10 * 4 + math.pi * 2 * 2) * 25.4**2
        self.assertAlmostEqual(face.Area, exact, 6)
        # the arcs bulge outward: the slot spans x from -2 to 12 inches
        self.assertAlmostEqual(sk.Shape.BoundBox.XMax, 12 * 25.4, 9)

    def test_file_units_and_missing_units(self):
        ents = "0\nLINE\n8\n0\n10\n0\n20\n0\n30\n0\n11\n1\n21\n0\n31\n0\n"
        sk, rep = self.insert(dxf_text(ents, insunits=1))
        self.assertAlmostEqual(sk.Geometry[0].length(), 25.4, 12)
        with self.assertRaises(SketcherDxf.DxfUnitsMissing):
            self.insert(dxf_text(ents, insunits=None))
        with self.assertRaises(SketcherDxf.DxfUnitsMissing):
            self.insert(dxf_text(ents, insunits=0))
        sk, rep = self.insert(dxf_text(ents, insunits=None), units="cm")
        self.assertAlmostEqual(sk.Geometry[0].length(), 10.0, 12)

    def test_blocks_nested_mirrored_arrayed(self):
        # block "B": an arc of radius 1 at (2, 0) from 0 to 90 degrees, base point (0, 0)
        # block "N": B inserted at (10, 0) rotated 90
        blocks = (
            "0\nBLOCK\n8\n0\n2\nB\n70\n0\n10\n0.0\n20\n0.0\n30\n0.0\n"
            "0\nARC\n8\n0\n10\n2.0\n20\n0.0\n30\n0.0\n40\n1.0\n50\n0.0\n51\n90.0\n0\nENDBLK\n8\n0\n"
            "0\nBLOCK\n8\n0\n2\nN\n70\n0\n10\n0.0\n20\n0.0\n30\n0.0\n"
            "0\nINSERT\n8\n0\n2\nB\n10\n10.0\n20\n0.0\n30\n0.0\n50\n90.0\n0\nENDBLK\n8\n0\n"
        )
        ents = (
            # N at the origin: the arc's centre at (10, 2), from (10, 3) to (9, 2)
            "0\nINSERT\n8\n0\n2\nN\n10\n0.0\n20\n0.0\n30\n0.0\n"
            # B mirrored in X (scale x -1) at (0, 20): centre (-2, 20), from (-3, 20) ... (-2, 21)
            "0\nINSERT\n8\n0\n2\nB\n10\n0.0\n20\n20.0\n30\n0.0\n41\n-1.0\n"
            # B by extrusion -Z (the mirror CAD tools write) at (0, 40): OCS x is world -x
            "0\nINSERT\n8\n0\n2\nB\n10\n0.0\n20\n40.0\n30\n0.0\n210\n0.0\n220\n0.0\n230\n-1.0\n"
            # B scaled 2 x 1 (non-uniform: an elliptical arc), 3 columns 5 apart, at (0, 60)
            "0\nINSERT\n8\n0\n2\nB\n10\n0.0\n20\n60.0\n30\n0.0\n41\n2.0\n70\n3\n44\n5.0\n"
        )
        sk, rep = self.insert(dxf_text(ents, blocks=blocks))
        g = sk.Geometry
        self.assertEqual(len(g), 6)

        def ends(geo):
            return sorted([(round(geo.StartPoint.x, 9), round(geo.StartPoint.y, 9)), (round(geo.EndPoint.x, 9), round(geo.EndPoint.y, 9))])

        self.assertEqual(g[0].TypeId, "Part::GeomArcOfCircle")
        self.assertEqual(ends(g[0]), [(9.0, 2.0), (10.0, 3.0)])
        self.assertEqual(ends(g[1]), [(-3.0, 20.0), (-2.0, 21.0)])
        self.assertEqual(ends(g[2]), [(-3.0, 40.0), (-2.0, 41.0)])
        for k in range(3):
            e = g[3 + k]
            self.assertEqual(e.TypeId, "Part::GeomArcOfEllipse")
            self.assertAlmostEqual(e.MajorRadius, 2.0, 12)
            self.assertAlmostEqual(e.MinorRadius, 1.0, 12)
            self.assertEqual(ends(e), [(round(4.0 + 5 * k, 9), 61.0), (round(6.0 + 5 * k, 9), 60.0)])
        # a mirrored arc still bulges away from its centre: the midpoint is on the circle
        mid = g[1].value(0.5 * (g[1].FirstParameter + g[1].LastParameter))
        self.assertAlmostEqual((mid - V(-2, 20, 0)).Length, 1.0, 12)
        self.assertLess(mid.x, -2.0)

    def test_old_polyline_text_paperspace(self):
        ents = (
            "0\nPOLYLINE\n8\n0\n66\n1\n70\n1\n"
            "0\nVERTEX\n8\n0\n10\n0.0\n20\n0.0\n0\nVERTEX\n8\n0\n10\n5.0\n20\n0.0\n0\nVERTEX\n8\n0\n10\n5.0\n20\n5.0\n"
            "0\nSEQEND\n8\n0\n"
            "0\nTEXT\n8\n0\n10\n0\n20\n0\n40\n2\n1\nhello\n"
            "0\nLINE\n67\n1\n8\n0\n10\n0\n20\n0\n30\n0\n11\n1\n21\n0\n31\n0\n"
        )
        sk, rep = self.insert(dxf_text(ents), fit=False)
        self.assertEqual(len(sk.Geometry), 3)
        self.assertEqual(rep.skipped, {"TEXT": 1})
        self.assertEqual(rep.paperspace, 1)
        self.assertAlmostEqual(Part.Face(sk.Shape.Wires[0]).Area, 12.5, 12)

    def test_refuses_binary_and_dwg(self):
        p = os.path.join(self.dir, "b.dxf")
        with open(p, "wb") as f:
            f.write(b"AutoCAD Binary DXF\r\n\x1a\x00rest")
        with self.assertRaises(SketcherDxf.DxfError):
            SketcherDxf.read(p)
        with open(p, "wb") as f:
            f.write(b"AC1032\x00\x00\x00")
        with self.assertRaises(SketcherDxf.DxfError):
            SketcherDxf.read(p)


class TestDxfFitting(unittest.TestCase):
    """The logo of 3,650 segments becomes about a hundred curves within the tolerance"""

    TOL = 0.01

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="dxf_")
        cls.loops = logo_loops()
        cls.path = write(cls.dir, "logo.dxf", dxf_text(lines_text(cls.loops)))

    def setUp(self):
        self.doc = FreeCAD.newDocument("DxfFit")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test_logo_has_3650_segments(self):
        self.assertEqual(sum(len(p) - 1 for p in self.loops), 3650)

    def test_fit(self):
        sk = new_sketch(self.doc)
        rep = SketcherDxf.insert(sk, self.path, tolerance=self.TOL)
        self.assertEqual(rep.segments, 3650)
        self.assertLessEqual(rep.curves, 150, rep)
        self.assertLessEqual(rep.max_deviation, self.TOL)
        self.assertEqual(rep.closed_chains, 5)
        self.assertEqual(rep.open_chains, 0)
        t = time.perf_counter()
        self.assertEqual(sk.solve(), 0)
        self.doc.recompute()
        self.assertLess(time.perf_counter() - t, 5.0)
        self.assertTrue(sk.isValid())
        wires, faces = sketch_faces(sk)
        self.assertEqual(len(wires), 5)
        self.assertTrue(all(w.isClosed() for w in wires))
        # each loop's area within its length times the tolerance of the polygon's
        areas = sorted(abs(f.Area) for f in faces)
        truth = sorted((abs(shoelace(p)), length(p)) for p in self.loops)
        for a, (ta, tl) in zip(areas, truth):
            self.assertLessEqual(abs(a - ta), tl * self.TOL, (a, ta))
        # the corners stay sharp: each is a vertex of the sketch
        verts = [v.Point for v in sk.Shape.Vertexes]
        for c in LOGO_CORNERS:
            self.assertLess(min((p - V(c[0], c[1], 0)).Length for p in verts), 1e-9, c)
        # the circle became arcs of radius 6, the rectangle four lines and four arcs of radius 2
        circles = [g for g in sk.Geometry if g.TypeId == "Part::GeomCircle"]
        self.assertEqual(len(circles), 1)
        self.assertAlmostEqual(circles[0].Radius, 6.0, 3)
        radii = sorted(round(g.Radius, 3) for g in sk.Geometry if g.TypeId == "Part::GeomArcOfCircle")
        self.assertEqual(radii.count(2.0), 4)

    def test_pocket_and_fillet_downstream(self):
        """The fitted logo pocketed 1 deep into a 120 x 120 x 10 pad, then the pad's 4 outer top
        edges filleted r 1 on the face that carries the pocket (kernel-robustness probe 2's case):
        the volume removed is the logo's net area (the shield less the four loops inside it)
        within the tolerance, and both features are quick (unfitted: 82 s and 32 s)."""
        doc = self.doc
        body = doc.addObject("PartDesign::Body", "Body")
        base = body.newObject("Sketcher::SketchObject", "Base")
        base.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        base.MapMode = "FlatFace"
        c = [(-60, -60), (60, -60), (60, 60), (-60, 60), (-60, -60)]
        for a, b in zip(c, c[1:]):
            base.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = base
        pad.Length = 10
        doc.recompute()
        sk = body.newObject("Sketcher::SketchObject", "Logo")
        sk.AttachmentSupport = [(pad, "Face6")]
        sk.MapMode = "FlatFace"
        SketcherDxf.insert(sk, self.path, tolerance=self.TOL)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sk
        pocket.Length = 1
        t = time.perf_counter()
        doc.recompute()
        self.assertLess(time.perf_counter() - t, 10.0)
        self.assertTrue(pocket.Shape.isValid())
        areas = sorted(abs(shoelace(p)) for p in self.loops)
        net = areas[-1] - sum(areas[:-1])
        tol_area = sum(length(p) for p in self.loops) * self.TOL
        self.assertLess(abs((pad.Shape.Volume - pocket.Shape.Volume) - net), tol_area)
        edges = []
        for i, e in enumerate(pocket.Shape.Edges):
            bb = e.BoundBox
            if abs(bb.ZMin - 10) < 1e-6 and abs(bb.ZMax - 10) < 1e-6 and (bb.XLength > 119 or bb.YLength > 119):
                edges.append(f"Edge{i + 1}")
        self.assertEqual(len(edges), 4)
        fil = body.newObject("PartDesign::Fillet", "Fillet")
        fil.Base = (pocket, edges)
        fil.Radius = 1
        t = time.perf_counter()
        doc.recompute()
        self.assertLess(time.perf_counter() - t, 10.0)
        self.assertTrue(fil.Shape.isValid())
        self.assertEqual(list(fil.State), ["Up-to-date"])

    def test_tolerance_is_honoured(self):
        sk = new_sketch(self.doc)
        rep = SketcherDxf.insert(sk, self.path, tolerance=0.001)
        self.assertLessEqual(rep.max_deviation, 0.001)
        coarse = SketcherDxf.insert(new_sketch(self.doc, "S2"), self.path, tolerance=0.05)
        self.assertLessEqual(coarse.curves, rep.curves)

    def test_no_fit_keeps_segments(self):
        sk = new_sketch(self.doc)
        rep = SketcherDxf.insert(sk, self.path, fit=False, hold="free")
        self.assertEqual(rep.curves, 3650)
        self.assertEqual(len(sk.Constraints), 0)

    def test_near_closed_gap(self):
        # a square whose last segment stops 0.004 short of the start: closed under 0.01
        pts = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.004)]
        ents = "".join(
            f"0\nLINE\n8\n0\n10\n{p[0]}\n20\n{p[1]}\n30\n0\n11\n{q[0]}\n21\n{q[1]}\n31\n0\n" for p, q in zip(pts, pts[1:])
        )
        path = write(self.dir, "gap.dxf", dxf_text(ents))
        sk = new_sketch(self.doc)
        rep = SketcherDxf.insert(sk, path, tolerance=0.01)
        self.assertEqual(rep.gaps_joined, 1)
        self.doc.recompute()
        self.assertTrue(sk.Shape.Wires[0].isClosed())
        # over the tolerance it stays open and is reported
        sk2 = new_sketch(self.doc, "S2")
        rep2 = SketcherDxf.insert(sk2, path, tolerance=0.001)
        self.assertEqual(rep2.gaps_joined, 0)
        self.assertEqual(rep2.open_chains, 1)


class TestDxfExport(unittest.TestCase):
    """A designed face and a sketch out to DXF, read back: arcs stay arcs, areas and loops agree"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dxf_")
        self.doc = FreeCAD.newDocument("DxfOut")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def plate(self):
        """60 x 40 x 5 box at (5, 7, 0), with a hole r 4, a slot 12 x 6 and an elliptical pocket
        through it; returns the shape and its top face"""
        box = Part.makeBox(60, 40, 5, V(5, 7, 0))
        hole = Part.makeCylinder(4, 5, V(20, 27, 0))
        slot_wire = Part.Wire(
            [
                Part.LineSegment(V(35, 17, 0), V(47, 17, 0)).toShape(),
                Part.Arc(V(47, 17, 0), V(50, 20, 0), V(47, 23, 0)).toShape(),
                Part.LineSegment(V(47, 23, 0), V(35, 23, 0)).toShape(),
                Part.Arc(V(35, 23, 0), V(32, 20, 0), V(35, 17, 0)).toShape(),
            ]
        )
        slot = Part.Face(slot_wire).extrude(V(0, 0, 5))
        ell = Part.Ellipse(V(52, 37, 0), 5, 2.5).toShape()
        pocket = Part.Face(Part.Wire(ell)).extrude(V(0, 0, 5))
        solid = box.cut(hole).cut(slot).cut(pocket)
        top = [f for f in solid.Faces if abs(f.CenterOfMass.z - 5) < 1e-9 and f.Surface.Axis.z != 0][0]
        return solid, top

    def entity_kinds(self, path):
        d = reader.read(path)
        kinds = {}
        for it in d.items:
            kinds[type(it).__name__] = kinds.get(type(it).__name__, 0) + 1
        return d, kinds

    def test_face_round_trip(self):
        solid, top = self.plate()
        path = os.path.join(self.dir, "face.dxf")
        rep = SketcherDxf.export_face(top, path, tolerance=0.01)
        self.assertEqual(rep.loops, 4)
        self.assertEqual(rep.closed_loops, 4)
        self.assertEqual(rep.entities["CIRCLE"], 1)
        self.assertGreaterEqual(rep.entities["ARC"], 2 + 4)  # the slot's two, the ellipse's arcs
        self.assertEqual(rep.approximated, 1)
        self.assertLessEqual(rep.max_deviation, 0.01)
        with open(path) as f:
            text = f.read()
        self.assertIn("$INSUNITS\n 70\n4\n", text)
        self.assertNotIn("LWPOLYLINE", text)
        d, kinds = self.entity_kinds(path)
        self.assertEqual(d.insunits, 4)
        self.assertEqual(kinds.get("Conic", 0), rep.entities["ARC"] + rep.entities["CIRCLE"])
        # back into a sketch (no fitting: the file has no segment chains to fit)
        sk = new_sketch(self.doc)
        SketcherDxf.insert(sk, path)
        self.doc.recompute()
        wires = sk.Shape.Wires
        self.assertEqual(len(wires), 4)
        self.assertTrue(all(w.isClosed() for w in wires))
        faces = sorted((Part.Face(w) for w in wires), key=lambda f: -f.Area)
        net = faces[0].Area - sum(f.Area for f in faces[1:])
        self.assertLess(abs(net - top.Area), 0.01 * top.Length)
        # seen from above at 1:1: the outer loop is the box's top, world X and Y
        bb = sk.Shape.BoundBox
        self.assertAlmostEqual(bb.XMin, 5.0, 9)
        self.assertAlmostEqual(bb.YMin, 7.0, 9)
        self.assertAlmostEqual(bb.XMax, 65.0, 9)
        self.assertAlmostEqual(bb.YMax, 47.0, 9)

    def test_bottom_and_side_faces(self):
        solid, top = self.plate()
        bottom = [f for f in solid.Faces if abs(f.CenterOfMass.z) < 1e-9 and f.Surface.Axis.z != 0][0]
        path = os.path.join(self.dir, "bottom.dxf")
        rep = SketcherDxf.export_face(bottom, path)
        self.assertEqual(rep.loops, 4)
        sk = new_sketch(self.doc)
        SketcherDxf.insert(sk, path)
        self.doc.recompute()
        # seen from below: mirrored in Y, the hole (world y 27) lands at -27
        circ = [g for g in sk.Geometry if g.TypeId == "Part::GeomCircle"][0]
        self.assertAlmostEqual(circ.Center.x, 20.0, 9)
        self.assertAlmostEqual(circ.Center.y, -27.0, 9)
        # a side face (normal -Y): world X across, world Z up
        side = [f for f in solid.Faces if abs(f.CenterOfMass.y - 7) < 1e-9][0]
        rep = SketcherDxf.export_face(side, os.path.join(self.dir, "side.dxf"))
        self.assertEqual(rep.entities["LINE"], 4)
        self.assertAlmostEqual(rep.size[0], 60.0, 9)
        self.assertAlmostEqual(rep.size[1], 5.0, 9)

    def test_polylines_option(self):
        solid, top = self.plate()
        path = os.path.join(self.dir, "poly.dxf")
        rep = SketcherDxf.export_face(top, path, polylines=True)
        self.assertEqual(rep.entities["POLYLINE"], 3)  # outer, slot, ellipse; the hole a CIRCLE
        self.assertEqual(rep.entities["CIRCLE"], 1)
        sk = new_sketch(self.doc)
        SketcherDxf.insert(sk, path, fit=False)
        self.doc.recompute()
        faces = sorted((Part.Face(w) for w in sk.Shape.Wires), key=lambda f: -f.Area)
        net = faces[0].Area - sum(f.Area for f in faces[1:])
        self.assertLess(abs(net - top.Area), 0.01 * top.Length)

    def test_sketch_export(self):
        sk = new_sketch(self.doc)
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(10, 5, 0), V(0, 0, 1), 5), -math.pi / 2, math.pi / 2))
        sk.addGeometry(Part.LineSegment(V(10, 10, 0), V(0, 10, 0)))
        sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(0, 0, 0)))
        sk.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2), True)  # construction: not exported
        sk.Placement = FreeCAD.Placement(V(100, 0, 50), FreeCAD.Rotation(V(1, 0, 0), 90))
        self.doc.recompute()
        path = os.path.join(self.dir, "sketch.dxf")
        rep = SketcherDxf.export_sketch(sk, path)
        self.assertEqual(rep.entities, {"LINE": 3, "ARC": 1, "CIRCLE": 0, "POLYLINE": 0})
        self.assertEqual(rep.closed_loops, 1)
        back = new_sketch(self.doc, "Back")
        SketcherDxf.insert(back, path)
        self.doc.recompute()
        self.assertAlmostEqual(Part.Face(back.Shape.Wires[0]).Area, 100 + math.pi * 12.5, 9)
        self.assertAlmostEqual(back.Shape.BoundBox.XMax, 15.0, 9)
