# fuzzplus.py: fuzz D+ (ops#640, robustness sweep rank 1). Designed geometry only.
# fuzz.py's studio and checks, plus:
#   * more edit kinds: sketch-topology edits (split a rectangle's edge / add or remove a circle, by redrawing the sketch),
#     suppress/unsuppress, delete + undo, and undo/redo of depth 1-10, all in GUI-style transactions;
#   * the fresh-rebuild check: after every step the document's state vector (every named sketch datum, every fuzzed
#     property, each sketch's variant, the suppressed set, the studio-list order) is built into a NEW document by the
#     template, with no edit history, and volume, area, solids and faces by surface type are compared with the edited
#     document. A history-dependent result (the ops#818 class) shows up as a difference.
# Verdicts for the fresh check: OK; WARN (only the face count by type differs); LOUD_LIVE / LOUD_FRESH / LOUD (red only in
# the edited document / only in the fresh build (a template pick) / both differ);
# BEYOND (a 1e-6 jitter of the vector changes the fresh result: a case boundary); SILENT (V or A differs, no error).
#
# The fresh build (FUZZ_FRESHMODE): jump (default) builds the template at its defaults, with the live document's own
# step-0 picks, and jumps to the state in one edit and one recompute: a LOUD_FRESH is then a real path dependence (ops#843).
# scratch builds the template at the state's values (re-picking edges there): its LOUD_FRESH is mostly pick noise.
# Undo history is keyed by unique transaction names (App caps its stack at 20 without a GUI). Suppress steps avoid the
# ops#592 state (a live pattern whose originals are all suppressed keeps a stale shape).
#
# Run: FUZZ_SEED=<n> FUZZ_STEPS=<n> [FUZZ_HEAL=1] [FUZZ_OUT=<dir>] FreeCADCmd tools/fuzz/fuzzplus.py
#   writes <out>/<tag>.jsonl and .sum. FUZZ_STOP=<k> saves the document after step k. FUZZ_FRESH=0 skips the fresh check.
import os, json, random, time, traceback
from collections import Counter
import FreeCAD as App
import Part, Sketcher, PartDesign

V = App.Vector
OUT = os.environ.get("FUZZ_OUT", os.path.join(os.getcwd(), "fuzz-out"))
os.makedirs(OUT, exist_ok=True)
SEED = int(os.environ.get("FUZZ_SEED", "1"))
STEPS = int(os.environ.get("FUZZ_STEPS", "200"))
STOP = int(os.environ.get("FUZZ_STOP", "0"))
TAG = os.environ.get("FUZZ_TAG", "plus%d" % SEED)
HEAL = os.environ.get("FUZZ_HEAL") == "1"
FRESH = os.environ.get("FUZZ_FRESH", "1") != "0"
FRESHMODE = os.environ.get("FUZZ_FRESHMODE", "jump")   # jump | scratch (see freshBuild)
STOPAT = set(x for x in os.environ.get("FUZZ_STOPAT", "").split(",") if x)   # e.g. SILENT,LOUD: end the seed at the first one
SAVED = [0]
LOG = open("%s/%s.jsonl" % (OUT, TAG), "w", buffering=1)

# step kinds and weights (sum 100)
KINDS = (("param", 45), ("move", 13), ("topo", 12), ("suppress", 8), ("delete", 8), ("undo", 14))


def emit(**kw):
    LOG.write(json.dumps(kw, default=str) + "\n")


# ------------------------------------------------------------------ sketches: a spec per sketch, drawn from values
# shape: ("rect", tag, x, y, w, h) | ("circle", tag, x, y, r) | ("point", tag, x, y); values are defaults, overridden by
# vals[<constraint name>]. Variants: "split" (the first rectangle's bottom edge in two collinear segments, the split
# at <tag>_split from its left end), "extra" (one more circle, tag X).
SPECS = {
    "BaseSk": (3, None, [("rect", "B", -60, -40, 120, 80)]),
    "Pk1Sk": (3, 20, [("rect", "P1", -52, -32, 20, 15)]),
    "Pk2Sk": (3, 20, [("rect", "P2", -18, -30, 10, 10)]),
    "HoleSk": (3, None, [("circle", "H", 28, 4, 3)]),
    "BossSk": (3, 10, [("circle", "C", -35, 18, 8)]),
    "RingSk": (4, None, [("rect", "R", 42, 10, 5, 4)]),
    "GrooveSk": (4, None, [("rect", "G", 53, 6, 3, 3)]),
    "RibSk": (3, 10, [("rect", "K1", -10, 20, 25, 3), ("rect", "K2", -10, 28, 25, 3)]),
    "HoleFSk": (3, 10, [("point", "Q", -45, 30)]),
    "SlotSk": (3, 20, [("rect", "S", 10, -38, 30, 4)]),
    "Boss2Sk": (3, 10, [("rect", "D", 14, -12, 10, 10)]),
    "LateSk": (3, 20, [("rect", "L", -6, -6, 12, 12)]),
    "BackSk": (3, 20, [("rect", "E", -30, 34, 24, 4)]),
    "TabSk": (3, 10, [("rect", "T", -58, -10, 8, 20)]),
}
EXTRA = {"HoleSk": ("circle", "X", 36, -4, 2), "BossSk": ("circle", "X", -35, 18, 3)}
TOPO = ["BaseSk", "Pk1Sk", "Pk2Sk", "SlotSk", "Boss2Sk", "LateSk", "BackSk", "TabSk", "RibSk", "HoleSk", "BossSk"]
SPLIT_FRAC = 0.35   # below every rectangle's w_min / w_max


def named(sk, c, name):
    i = sk.addConstraint(c)
    sk.renameConstraint(i, name)
    return i


def drawRect(sk, tag, x, y, w, h, split=None):
    f = len(sk.Geometry)
    if split is None:
        pts = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
        hz, vt, right = (f, f + 2), (f + 1, f + 3), f + 1
    else:
        pts = [V(x, y, 0), V(x + split, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
        hz, vt, right = (f, f + 1, f + 3), (f + 2, f + 4), f + 2
    n = len(pts)
    for i in range(n):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % n]), False)
    for i in range(n):
        sk.addConstraint(Sketcher.Constraint("Coincident", f + i, 2, f + (i + 1) % n, 1))
    for g in hz:
        sk.addConstraint(Sketcher.Constraint("Horizontal", g))
    for g in vt:
        sk.addConstraint(Sketcher.Constraint("Vertical", g))
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, f, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, f, 1, y), tag + "y")
    if split is None:
        named(sk, Sketcher.Constraint("DistanceX", f, 1, f, 2, w), tag + "w")
    else:
        named(sk, Sketcher.Constraint("DistanceX", f, 1, f + 1, 2, w), tag + "w")
        named(sk, Sketcher.Constraint("DistanceX", f, 1, f, 2, split), tag + "_split")
    named(sk, Sketcher.Constraint("DistanceY", right, 1, right, 2, h), tag + "h")


def drawCircle(sk, tag, x, y, r):
    g = sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 3, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 3, y), tag + "y")
    named(sk, Sketcher.Constraint("Radius", g, r), tag + "r")


def drawPoint(sk, tag, x, y):
    g = sk.addGeometry(Part.Point(V(x, y, 0)), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 1, y), tag + "y")


def drawSketch(sk, vals, variant):
    shapes = list(SPECS[sk.Name][2])
    if variant == "extra":
        shapes.append(EXTRA[sk.Name])
    for j, s in enumerate(shapes):
        kind, tag, d = s[0], s[1], s[2:]
        g = lambda k, dv: vals.get(tag + k, dv)
        if kind == "rect":
            x, y, w, h = g("x", d[0]), g("y", d[1]), g("w", d[2]), g("h", d[3])
            split = None
            if j == 0 and variant == "split":
                split = vals.get(tag + "_split", round(SPLIT_FRAC * w, 4))
            drawRect(sk, tag, x, y, w, h, split)
        elif kind == "circle":
            drawCircle(sk, tag, g("x", d[0]), g("y", d[1]), g("r", d[2]))
        else:
            drawPoint(sk, tag, g("x", d[0]), g("y", d[1]))


def sketchVals(sk):
    return {c.Name: c.Value for c in sk.Constraints if c.Name}


def sketchVariant(sk):
    names = {c.Name for c in sk.Constraints if c.Name}
    if any(n.endswith("_split") for n in names):
        return "split"
    if "Xr" in names:
        return "extra"
    return ""


# ------------------------------------------------------------------ the template: builds the studio from a state vector
class Studio:
    PATTERNS = ("LinearPattern", "PolarPattern", "Mirrored")

    def __init__(self, doc, state=None):
        self.doc = doc
        st = state or {}
        self.vals = st.get("vals", {})        # "<sketch>.<constraint>" -> mm
        self.props = st.get("props", {})      # "<feature>.<property>" -> value
        self.variants = st.get("variants", {})
        self.body = doc.addObject("PartDesign::Body", "Plate")
        self.o = self.body.Origin.OriginFeatures   # X_Axis Y_Axis Z_Axis XY XZ YZ
        self.params = []    # (object name, kind, key, lo, hi, integer)

    def v(self, sk, key, dv):
        return self.vals.get("%s.%s" % (sk, key), dv)

    def pv(self, f, key, dv):
        return self.props.get("%s.%s" % (f, key), dv)

    def sk(self, name):
        plane, z, _ = SPECS[name]
        s = self.body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(self.o[plane], "")]
        s.MapMode = "FlatFace"
        if z is not None:
            s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        PartDesign.studioInsert(s, -1)
        pre = name + "."
        drawSketch(s, {k[len(pre):]: x for k, x in self.vals.items() if k.startswith(pre)}, self.variants.get(name, ""))
        return s

    def feat(self, kind, name, **props):
        props = {k: self.pv(name, k, x) for k, x in props.items()}
        if kind in self.PATTERNS:
            f = self.doc.addObject("PartDesign::" + kind, name)
            for k, x in props.items():
                setattr(f, k, x)
            self.body.addObject(f)
        else:
            f = self.body.newObject("PartDesign::" + kind, name)
            for k, x in props.items():
                setattr(f, k, x)
        PartDesign.studioInsert(f, -1)
        self.doc.recompute()
        return f

    def p(self, obj, key, lo, hi, kind="datum", integer=False):
        self.params.append((obj.Name, kind, key, lo, hi, integer))

    @staticmethod
    def edgesWhere(feature, pred):
        return ["Edge%d" % i for i, e in enumerate(feature.Shape.Edges, 1) if pred(e)]

    def mapEdges(self, src, last, names):
        out = []
        sh = last.Shape
        for n in names:
            c = src.Shape.getElement(n).CenterOfMass
            for i, e in enumerate(sh.Edges, 1):
                if (e.CenterOfMass - c).Length < 1e-6:
                    out.append("Edge%d" % i)
                    break
        return out

    def build(self):
        doc, o = self.doc, self.o
        E = 1e-6
        PartDesign.studioList(doc, True)
        s = self.sk("BaseSk")
        self.p(s, "Bw", 110, 130); self.p(s, "Bh", 75, 90)
        base = self.feat("Pad", "Base", Profile=s, Length=10); self.p(base, "Length", 10, 14, "prop")   # under 10 the z=10 bosses float off the plate
        s = self.sk("Pk1Sk")
        self.p(s, "P1x", -55, -45); self.p(s, "P1w", 14, 24); self.p(s, "P1h", 10, 18)
        pk1 = self.feat("Pocket", "Pocket1", Profile=s, Length=14); self.p(pk1, "Length", 12, 16, "prop")
        s = self.sk("Pk2Sk")
        self.p(s, "P2x", -22, -14); self.p(s, "P2w", 6, 12)
        pk2 = self.feat("Pocket", "Pocket2", Profile=s, Length=13); self.p(pk2, "Length", 11.5, 15, "prop")
        lp = self.feat("LinearPattern", "LinPat", Originals=[pk2], Direction=(o[0], [""]), Length=40, Occurrences=3)
        self.p(lp, "Length", 30, 48, "prop"); self.p(lp, "Occurrences", 2, 4, "prop", True)
        s = self.sk("HoleSk")
        self.p(s, "Hx", 24, 32); self.p(s, "Hr", 2, 4)
        hole = self.feat("Pocket", "ThruHole", Profile=s, Type="ThroughAll", SideType="Symmetric")
        pp = self.feat("PolarPattern", "PolPat", Originals=[hole], Axis=(o[2], [""]), Angle=360, Occurrences=6)
        self.p(pp, "Occurrences", 3, 8, "prop", True)
        s = self.sk("BossSk")
        self.p(s, "Cx", -40, -30); self.p(s, "Cy", 14, 22); self.p(s, "Cr", 5, 10)
        boss = self.feat("Pad", "Boss", Profile=s, Length=8); self.p(boss, "Length", 4, 12, "prop")
        self.feat("Mirrored", "MirBoss", Originals=[boss], MirrorPlane=(o[5], [""]))
        s = self.sk("RingSk")
        self.p(s, "Rx", 40, 46); self.p(s, "Rw", 3, 6); self.p(s, "Rh", 2, 6)
        self.feat("Revolution", "Ring", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        s = self.sk("GrooveSk")
        self.p(s, "Gx", 52, 55); self.p(s, "Gy", 4, 7)
        self.feat("Groove", "Groove", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        s = self.sk("RibSk")
        self.p(s, "K1w", 15, 30); self.p(s, "K2y", 26, 32)
        ribs = self.feat("Pad", "Ribs", Profile=s, Length=4); self.p(ribs, "Length", 2, 7, "prop")
        lp2 = self.feat("LinearPattern", "RibPat", Originals=[ribs], Direction=(o[1], [""]), Reversed=True, Length=40, Occurrences=2)
        self.p(lp2, "Length", 36, 46, "prop")
        s = self.sk("HoleFSk")
        self.p(s, "Qx", -50, -42); self.p(s, "Qy", 26, 33)
        hf = self.feat("Hole", "CBHole", Profile=s, Diameter=5, Depth=7, DepthType="Dimension",
                       HoleCutType="Counterbore", HoleCutDiameter=9, HoleCutDepth=2)
        self.p(hf, "Diameter", 3, 6, "prop"); self.p(hf, "Depth", 4, 9, "prop")
        pp2 = self.feat("PolarPattern", "CBPat", Originals=[hf], Axis=(o[2], [""]), Angle=360, Occurrences=4)
        self.p(pp2, "Occurrences", 2, 5, "prop", True)
        s = self.sk("SlotSk")
        self.p(s, "Sx", 5, 15); self.p(s, "Sw", 20, 34); self.p(s, "Sh", 3, 6)
        slot = self.feat("Pocket", "Slot", Profile=s, Length=12); self.p(slot, "Length", 11, 14, "prop")
        self.feat("Mirrored", "MirSlot", Originals=[slot], MirrorPlane=(o[4], [""]))
        s = self.sk("Boss2Sk")
        self.p(s, "Dx", 12, 16); self.p(s, "Dw", 7, 10)
        boss2 = self.feat("Pad", "Boss2", Profile=s, Length=6); self.p(boss2, "Length", 3, 10, "prop")
        doc.recompute()
        # dress-up picks follow the parameters (the user's intent at these values)
        Dx, Dy = self.v("Boss2Sk", "Dx", 14), self.v("Boss2Sk", "Dy", -12)
        Dw, Dh = self.v("Boss2Sk", "Dw", 10), self.v("Boss2Sk", "Dh", 10)
        ztop2 = 10 + float(boss2.Length)
        inD = lambda p: Dx - E < p.x < Dx + Dw + E and Dy - E < p.y < Dy + Dh + E
        sh = boss2.Shape
        def onSide(f):
            bb = f.BoundBox
            if abs(f.normalAt(0, 0).z) > 1e-6 or bb.ZMin < 10 - E or bb.ZMax > ztop2 + E:
                return False
            xs = (abs(bb.XMin - Dx) < E and abs(bb.XMax - Dx) < E) or (abs(bb.XMin - Dx - Dw) < E and abs(bb.XMax - Dx - Dw) < E)
            ys = (abs(bb.YMin - Dy) < E and abs(bb.YMax - Dy) < E) or (abs(bb.YMin - Dy - Dh) < E and abs(bb.YMax - Dy - Dh) < E)
            return (xs and bb.YMin > Dy - E and bb.YMax < Dy + Dh + E) or (ys and bb.XMin > Dx - E and bb.XMax < Dx + Dw + E)
        sides = ["Face%d" % i for i, f in enumerate(sh.Faces, 1) if onSide(f)]
        topf = ["Face%d" % i for i, f in enumerate(sh.Faces, 1)
                if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - ztop2) < 1e-6 and inD(f.CenterOfMass)]
        dr = self.feat("Draft", "Boss2Draft", Base=(boss2, sides), NeutralPlane=(boss2, topf[:1]), Angle=3)
        self.p(dr, "Angle", 1, 6, "prop")
        doc.recompute()
        Bx, By = self.v("BaseSk", "Bx", -60), self.v("BaseSk", "By", -40)
        Bw, Bh = self.v("BaseSk", "Bw", 120), self.v("BaseSk", "Bh", 80)
        corner = lambda p: min(abs(p.x - Bx), abs(p.x - Bx - Bw)) < E and min(abs(p.y - By), abs(p.y - By - Bh)) < E
        vert = self.edgesWhere(base, lambda e: abs(e.Vertexes[0].Point.z - e.Vertexes[-1].Point.z) > 5 and corner(e.Vertexes[0].Point))
        last = self.body.Tip
        f1 = self.feat("Fillet", "CornerFillet", Base=(last, self.mapEdges(base, last, vert)), Radius=4)
        self.p(f1, "Radius", 2, 6, "prop")
        doc.recompute()
        top = self.edgesWhere(boss2, lambda e: all(abs(x.Point.z - ztop2) < 1e-6 and inD(x.Point) for x in e.Vertexes))
        last = self.body.Tip
        c1 = self.feat("Chamfer", "Boss2Chamfer", Base=(last, self.mapEdges(boss2, last, top)), Size=1)
        self.p(c1, "Size", 0.5, 2, "prop")
        doc.recompute()
        zb = 10 + float(boss.Length)
        Cx, Cy, Cr = self.v("BossSk", "Cx", -35), self.v("BossSk", "Cy", 18), self.v("BossSk", "Cr", 8)
        rim = self.edgesWhere(boss, lambda e: hasattr(e.Curve, "Radius") and all(abs(x.Point.z - zb) < 1e-6 for x in e.Vertexes)
                              and abs(e.Curve.Center.x - Cx) < 1e-6 and abs(e.Curve.Center.y - Cy) < 1e-6 and abs(e.Curve.Radius - Cr) < 1e-6)
        last = self.body.Tip
        f2 = self.feat("Fillet", "BossFillet", Base=(last, self.mapEdges(boss, last, rim)), Radius=1.5)
        self.p(f2, "Radius", 0.5, 3, "prop")
        doc.recompute()
        P1x, P1y = self.v("Pk1Sk", "P1x", -52), self.v("Pk1Sk", "P1y", -32)
        P1w, P1h = self.v("Pk1Sk", "P1w", 20), self.v("Pk1Sk", "P1h", 15)
        zt = float(base.Length)
        in1 = lambda p: P1x - E < p.x < P1x + P1w + E and P1y - E < p.y < P1y + P1h + E
        rim1 = self.edgesWhere(pk1, lambda e: all(abs(x.Point.z - zt) < 1e-6 and in1(x.Point) for x in e.Vertexes))
        last = self.body.Tip
        c2 = self.feat("Chamfer", "Pk1Chamfer", Base=(last, self.mapEdges(pk1, last, rim1)), Size=0.8)
        self.p(c2, "Size", 0.3, 1.5, "prop")
        doc.recompute()
        s = self.sk("LateSk")
        self.p(s, "Lw", 6, 16); self.p(s, "Lx", -8, -4)
        late = self.feat("Pocket", "LatePocket", Profile=s, Length=12); self.p(late, "Length", 11, 14, "prop")
        doc.recompute()
        s = self.sk("BackSk")
        self.p(s, "Ex", -34, -26); self.p(s, "Ew", 16, 28)
        back = self.feat("Pocket", "BackSlot", Profile=s, Length=12.5); self.p(back, "Length", 11, 14, "prop")
        s = self.sk("TabSk")
        self.p(s, "Ty", -14, -6); self.p(s, "Th", 12, 24)
        tab = self.feat("Pad", "Tab", Profile=s, Length=5); self.p(tab, "Length", 2, 9, "prop")
        Tx, Tw = self.v("TabSk", "Tx", -58), self.v("TabSk", "Tw", 8)
        zT = 10 + float(tab.Length)
        edges = self.edgesWhere(tab, lambda e: all(abs(x.Point.z - zT) < 1e-6 and x.Point.x < Tx + Tw + 1 for x in e.Vertexes))
        last = self.body.Tip
        c3 = self.feat("Chamfer", "TabChamfer", Base=(last, self.mapEdges(tab, last, edges)), Size=0.6)
        self.p(c3, "Size", 0.3, 1.2, "prop")
        self.features = [x for x in self.body.Group if x.isDerivedFrom("PartDesign::Feature")]
        return self

    def applyStructure(self, state):
        """the suppressed set and the list order of state; returns a note when the order can't be reached"""
        doc = self.doc
        for n in state.get("suppressed", []):
            PartDesign.studioSuppress(doc.getObject(n), True)
        note = None
        target = state.get("order")
        if target:
            for i, n in enumerate(target):
                cur = [e.Name for e in PartDesign.studioList(doc).Entries]
                if i < len(cur) and cur[i] != n and n in cur:
                    try:
                        PartDesign.studioMove(doc.getObject(n), i)
                    except ValueError as x:
                        note = "order: move %s -> %d refused (%s)" % (n, i, x)
                        break
            cur = [e.Name for e in PartDesign.studioList(doc).Entries]
            if note is None and cur != target:
                note = "order not reached"
        doc.recompute()
        return note


# ------------------------------------------------------------------ state vector and signatures
def stateOf(doc, params):
    vals, variants = {}, {}
    for n in SPECS:
        sk = doc.getObject(n)
        if sk is None:
            continue
        for k, x in sketchVals(sk).items():
            vals["%s.%s" % (n, k)] = x
        variants[n] = sketchVariant(sk)
    props = {}
    for name, kind, key, lo, hi, integer in params:
        if kind == "prop":
            o = doc.getObject(name)
            if o is None:
                continue
            x = getattr(o, key)
            props["%s.%s" % (name, key)] = int(x) if integer else float(getattr(x, "Value", x))
    body = doc.getObject("Plate")
    sup = sorted(o.Name for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and getattr(o, "Suppressed", False))
    lst = PartDesign.studioList(doc)
    return dict(vals=vals, props=props, variants=variants, suppressed=sup,
                order=[e.Name for e in lst.Entries] if lst is not None else None)


def signature(doc):
    body = doc.getObject("Plate")
    out = {}
    sh = body.Shape
    out["null"] = sh.isNull()
    if not sh.isNull():
        out.update(valid=sh.isValid(), solids=len(sh.Solids), faces=len(sh.Faces), edges=len(sh.Edges),
                   vol=sh.Volume, area=sh.Area,
                   ftypes=dict(Counter(type(f.Surface).__name__ for f in sh.Faces)))
        try:
            em = sh.ElementReverseMap
        except Exception:
            em = None
        if em is None:
            em = {}
            for k, x in sh.ElementMap.items():
                em.setdefault(x, k)
        names = {}
        for i, f in enumerate(sh.Faces, 1):
            n = em.get("Face%d" % i)
            if isinstance(n, (list, tuple)):
                n = sorted(n)[0] if n else None
            c = f.CenterOfMass
            names[str(n)] = (round(f.Area, 6), round(c.x, 5), round(c.y, 5), round(c.z, 5))
        out["faces_by_name"] = names
        out["named"] = sum(1 for k in names if k != "None")
    feats = {}
    for o in body.Group:
        if o.isDerivedFrom("PartDesign::Feature"):
            s = o.Shape
            feats[o.Name] = (("Invalid" in o.State) or ("Error" in o.State),
                             None if s.isNull() else round(s.Volume, 6), "Suppressed" if getattr(o, "Suppressed", False) else "")
    out["features"] = feats
    out["order"] = [o.Name for o in body.Group]
    lst = PartDesign.studioList(doc)
    out["list"] = [e.Name for e in lst.Entries] if lst is not None else None
    out["errors"] = sorted(o.Name for o in doc.Objects if "Invalid" in o.State or "Error" in o.State)
    out["warnings"] = sorted(o.Name for o in doc.Objects if "Warning" in o.State)
    return out


def compare(a, b):
    diffs = []
    for k in ("null", "valid", "solids", "faces", "edges"):
        if a.get(k) != b.get(k):
            diffs.append("%s %s != %s" % (k, a.get(k), b.get(k)))
    if a.get("vol") is not None and b.get("vol") is not None and abs(a["vol"] - b["vol"]) > 1e-6:
        diffs.append("vol %.9f != %.9f (d %.3g)" % (a["vol"], b["vol"], a["vol"] - b["vol"]))
    fa, fb = a.get("faces_by_name", {}), b.get("faces_by_name", {})
    if fa != fb:
        only_a = sorted(set(fa) - set(fb)); only_b = sorted(set(fb) - set(fa))
        moved = [n for n in set(fa) & set(fb) if fa[n] != fb[n]]
        diffs.append("names: %d only a, %d only b, %d on other faces; e.g. a %s b %s moved %s"
                     % (len(only_a), len(only_b), len(moved), only_a[:2], only_b[:2], moved[:2]))
    for n in sorted(set(a["features"]) | set(b["features"])):
        if a["features"].get(n) != b["features"].get(n):
            diffs.append("feature %s %s != %s" % (n, a["features"].get(n), b["features"].get(n)))
    if a["errors"] != b["errors"]:
        diffs.append("errors %s != %s" % (a["errors"], b["errors"]))
    if a.get("warnings") != b.get("warnings"):
        diffs.append("warnings %s != %s" % (a.get("warnings"), b.get("warnings")))
    if a.get("list") != b.get("list"):
        diffs.append("list differs")
    return diffs


def geomDiffs(a, b):
    """fresh-check comparison: geometry and error states only (names are per document)"""
    d = {}
    if a.get("null") != b.get("null"):
        d["null"] = (a.get("null"), b.get("null"))
        return d
    if a.get("null"):
        return d
    for k in ("valid", "solids"):
        if a.get(k) != b.get(k):
            d[k] = (a.get(k), b.get(k))
    va, vb = a["vol"], b["vol"]
    if abs(va - vb) > 1e-6 * max(1.0, abs(va)):
        d["vol"] = (round(va, 6), round(vb, 6))
    aa, ab = a["area"], b["area"]
    if abs(aa - ab) > 1e-5 * max(1.0, abs(aa)):
        d["area"] = (round(aa, 6), round(ab, 6))
    if a["ftypes"] != b["ftypes"]:
        d["ftypes"] = (a["ftypes"], b["ftypes"])
    ea = sorted(n for n, x in a["features"].items() if x[0]); eb = sorted(n for n, x in b["features"].items() if x[0])
    if ea != eb:
        d["red"] = (ea, eb)
    return d


def fullFrom(doc):
    import shutil
    path = "%s/%s-cur.FCStd" % (OUT, TAG)
    copy = "%s/%s-full.FCStd" % (OUT, TAG)
    doc.saveAs(path)
    shutil.copyfile(path, copy)
    d2 = App.openDocument(copy)
    try:
        for o in d2.Objects:
            o.touch()
        t0 = time.perf_counter(); d2.recompute(); t = time.perf_counter() - t0
        return signature(d2), t
    finally:
        App.closeDocument(d2.Name)


def jitter(state, eps, rng):
    s = json.loads(json.dumps(state))
    for k in s["vals"]:
        s["vals"][k] += eps * rng.choice((-1, 1))
    for k, x in s["props"].items():
        if isinstance(x, float):
            s["props"][k] = x + eps * rng.choice((-1, 1))
    return s


def jumpTo(d, st, state):
    """FUZZ_FRESHMODE=jump: from the default build (the live document's own step-0 picks), every value, variant and
    property of state in one edit and one recompute"""
    for n in SPECS:
        sk = d.getObject(n)
        pre = n + "."
        want = {k[len(pre):]: x for k, x in state["vals"].items() if k.startswith(pre)}
        var = state["variants"].get(n, "")
        if var != sketchVariant(sk):
            sk.deleteAllGeometry()
            drawSketch(sk, want, var)
            continue
        cur = sketchVals(sk)
        for k, x in want.items():
            if k in cur and abs(cur[k] - x) > 1e-12:
                sk.setDatum(datumKey(sk, k), App.Units.Quantity("%.12g mm" % x))
    for k, x in state["props"].items():
        n, key = k.split(".", 1)
        o = d.getObject(n)
        if o is not None:
            setattr(o, key, x)
    d.recompute()
    return st.applyStructure(state)


def freshBuild(state):
    """the state built into a new document with no edit history: (signature, note, seconds).
    FUZZ_FRESHMODE=scratch builds the template at the state's values (the picks follow those values, so a pick can
    differ from the live document's: LOUD_FRESH noise); jump (the default) builds at the defaults and jumps to the state
    in one edit, so the picks are the live document's and any difference is the edit path's (ops#640, scout 2)"""
    t0 = time.perf_counter()
    d = App.newDocument("Fresh")
    try:
        if FRESHMODE == "scratch":
            st = Studio(d, state).build()
            note = st.applyStructure(state)
        else:
            st = Studio(d).build()
            PartDesign.studioList(d, True)
            d.recompute()
            note = jumpTo(d, st, state)
        return signature(d), note, time.perf_counter() - t0
    finally:
        App.closeDocument(d.Name)


def freshCheck(doc, live, params, k):
    state = stateOf(doc, params)
    fsig, note, t = freshBuild(state)
    d = geomDiffs(live, fsig)
    rec = dict(fresh_s=round(t, 3))
    if note:
        rec["fresh_note"] = note
    if not d:
        rec["fresh"] = "OK"
        return rec, state
    rec["fresh_diff"] = d
    if "red" in d or "null" in d:
        if "red" in d:   # LOUD_LIVE: the edited document has a red feature the fresh build doesn't (the candidate kind)
            live_only = set(d["red"][0]) - set(d["red"][1]); fresh_only = set(d["red"][1]) - set(d["red"][0])
            rec["fresh"] = "LOUD_LIVE" if live_only and not fresh_only else "LOUD_FRESH" if fresh_only and not live_only else "LOUD"
        else:
            rec["fresh"] = "LOUD"
    elif set(d) <= {"ftypes"}:
        rec["fresh"] = "WARN"
    else:
        jr = random.Random(k)
        flips = []
        for _ in range(2):
            js, _n, _t = freshBuild(jitter(state, 1e-6, jr))
            jd = {x: y for x, y in geomDiffs(fsig, js).items() if x != "ftypes"}   # only V, A or red flips mark a boundary
            if jd:
                flips.append(jd)
        rec["fresh"] = "BEYOND" if flips else "SILENT"
        if flips:
            rec["jitter"] = flips[:1]
    return rec, state


# ------------------------------------------------------------------ edit steps (each in a transaction, recompute inside)
def datumKey(sk, name):
    for i, c in enumerate(sk.Constraints):
        if c.Name == name:
            return i
    raise KeyError(name)


def stepParam(doc, rng, params):
    name, kind, key, lo, hi, integer = rng.choice(params)
    obj = doc.getObject(name)
    v = rng.randint(int(lo), int(hi)) if integer else round(rng.uniform(lo, hi), 2)
    if kind == "datum":
        obj.setDatum(datumKey(obj, key), App.Units.Quantity("%s mm" % v))
    else:
        setattr(obj, key, v)
    return "%s.%s = %s" % (name, key, v)


def movable(doc):
    entries = list(PartDesign.studioList(doc).Entries)
    return entries, [e for e in entries if e.isDerivedFrom("PartDesign::Feature") or e.isDerivedFrom("Sketcher::SketchObject")]


def stepMove(doc, rng):
    entries, mv = movable(doc)
    e = rng.choice(mv)
    i = entries.index(e)
    j = i + rng.choice((-1, 1))
    if j < 0 or j >= len(entries):
        j = i - (j - i)
    PartDesign.studioMove(e, j)   # ValueError: refused (the caller aborts the transaction)
    after = [x.Name for x in PartDesign.studioList(doc).Entries]
    return "move %s %d -> %d%s" % (e.Name, i, j, "" if after.index(e.Name) == j else " (at %d)" % after.index(e.Name))


def stepTopo(doc, rng):
    n = rng.choice(TOPO)
    sk = doc.getObject(n)
    vals, var = sketchVals(sk), sketchVariant(sk)
    if n in EXTRA:
        new = "" if var == "extra" else "extra"
    else:
        new = "" if var == "split" else "split"
    if new != "extra":
        vals = {k: x for k, x in vals.items() if not k.startswith("X")}
    sk.deleteAllGeometry()
    drawSketch(sk, vals, new)
    return "topo %s %s -> %s" % (n, var or "plain", new or "plain")


def stepSuppress(doc, rng):
    body = doc.getObject("Plate")
    feats = [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and o.Name != "Base"]
    sup = [o for o in feats if getattr(o, "Suppressed", False)]
    # unsuppress more often when several are off, so the model stays mostly whole
    offn = {y.Name for y in sup}
    back = [x for x in sup if not (getattr(x, "Originals", None) and all(q.Name in offn for q in x.Originals))]   # ops#592
    if back and rng.random() < min(0.8, 0.3 * len(sup)):
        o = rng.choice(back); on = False
    else:
        # never leave a live pattern with all its originals suppressed: that is ops#592 (filed, deferred), whose stale
        # shape would turn every later comparison of the seed into noise
        def orphans(x):
            off = {y.Name for y in sup} | {x.Name}
            return any(not getattr(p, "Suppressed", False) and p.Name not in off and getattr(p, "Originals", None)
                       and all(q.Name in off for q in p.Originals) for p in feats)
        o = rng.choice([x for x in feats if not getattr(x, "Suppressed", False) and not orphans(x)]); on = True
    PartDesign.studioSuppress(o, on)
    return "%s %s" % ("suppress" if on else "unsuppress", o.Name)


def stepDelete(doc, rng):
    _entries, mv = movable(doc)
    e = rng.choice([x for x in mv if x.Name not in ("Base", "BaseSk")])
    n = e.Name
    PartDesign.studioRemove(e)
    doc.removeObject(n)
    return "delete %s" % n


TSEQ = [0]


def transact(doc, fn, *a):
    """one GUI-style transaction; returns (what, recompute seconds, the transaction's name if it was committed, else
    None). App caps its undo stack at 20 without a GUI (Document::setMaxUndoStackSize, not exposed to Python), so
    UndoCount stops growing at the cap: a commit is found by its unique name in UndoNames instead."""
    TSEQ[0] += 1
    name = "fuzz%d" % TSEQ[0]
    doc.openTransaction(name)
    try:
        what = fn(doc, *a)
        t0 = time.perf_counter(); doc.recompute(); dt = time.perf_counter() - t0
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return what, dt, name if name in list(doc.UndoNames) else None


def main():
    rng = random.Random(SEED)
    doc = App.newDocument("Fuzz")
    doc.UndoMode = 1
    t0 = time.perf_counter()
    st = Studio(doc).build()
    PartDesign.studioList(doc, True)
    doc.recompute()
    params = st.params
    sig0 = signature(doc)
    emit(step=0, what="build", wall_s=round(time.perf_counter() - t0, 3), vol=sig0.get("vol"), faces=sig0.get("faces"),
         errors=sig0["errors"], nlist=len(sig0["list"] or []))
    full0, tf = fullFrom(doc)
    rec0 = dict(step=0, what="build checks", diffs=compare(sig0, full0), full_s=round(tf, 3))
    if FRESH:
        r, _s = freshCheck(doc, sig0, params, 0)
        rec0.update(r)
    emit(**rec0)
    hist = {"build": sig0}   # transaction name -> the signature after it ("build": before any)
    top = sig0                 # the signature of the current state
    ncommit = 0
    tally = Counter(); times = []; fails = 0
    base_err = sig0["errors"]
    names = [k for k, _w in KINDS]; weights = [w for _k, w in KINDS]
    for k in range(1, STEPS + 1):
        kind = rng.choices(names, weights)[0]
        r2 = random.Random(rng.random())
        rec = dict(step=k, kind=kind)
        before = top
        try:
            if kind == "undo":
                unames = list(doc.UndoNames)   # the most recent first
                # undoing d steps leaves unames[d] on top, or the build when the stack held every commit
                depth = min(r2.randint(1, 10), doc.UndoCount)
                tgt = unames[depth] if depth < len(unames) else ("build" if ncommit == len(unames) else None)
                if depth < 1 or tgt is None or tgt not in hist or unames[0] not in hist:
                    rec["what"] = "undo: nothing to undo" if depth < 1 else "undo: target not recorded"
                    rec["undo_names"] = unames[:depth + 1]; emit(**rec); continue
                for _ in range(depth):
                    doc.undo()
                doc.recompute()
                s_u = signature(doc)
                du = compare(s_u, hist[tgt])
                for _ in range(depth):
                    doc.redo()
                doc.recompute()
                s_r = signature(doc)
                dr = compare(s_r, top)
                rec.update(what="undo %d + redo %d" % (depth, depth), undo_diffs=du, redo_diffs=dr, undo_to=tgt)
                if du or dr:
                    fails += 1; tally["undo_fail"] += 1
                    rec["undo_matches"] = [n for n, h in hist.items() if not compare(s_u, h)]   # the states that would match
                    rec["undo_count"] = doc.UndoCount; rec["undo_names"] = unames[:depth + 1]
                    doc.saveAs("%s/%s-fail%d.FCStd" % (OUT, TAG, k))
                emit(**rec); continue
            fn = {"param": lambda d: stepParam(d, r2, params), "move": lambda d: stepMove(d, r2),
                  "topo": lambda d: stepTopo(d, r2), "suppress": lambda d: stepSuppress(d, r2),
                  "delete": lambda d: stepDelete(d, r2)}[kind]
            what, dt, committed = transact(doc, fn)
            rec.update(what=what, inc_s=round(dt, 3)); times.append(dt)
        except ValueError as e:
            rec.update(what="refused", refused=str(e)); emit(**rec); continue
        except Exception as e:
            rec["exc"] = "%s: %s" % (type(e).__name__, e); rec["tb"] = traceback.format_exc().splitlines()[-3:]
            fails += 1; tally["exc"] += 1
            emit(**rec)
            continue
        try:
            inc = signature(doc)
            full, tf = fullFrom(doc)
            diffs = compare(inc, full)
            rec.update(full_s=round(tf, 3), vol=inc.get("vol"), faces=inc.get("faces"), errors=inc["errors"], diffs=diffs)
            if diffs:
                fails += 1; tally["full_fail"] += 1
            if FRESH and kind != "delete":
                r, state = freshCheck(doc, inc, params, k)
                rec.update(r)
                tally["fresh_" + r["fresh"]] += 1
                if r["fresh"] not in ("OK",):
                    rec["state"] = state
            if (diffs or rec.get("fresh") in ("SILENT", "LOUD", "LOUD_LIVE")) and SAVED[0] < 5:
                SAVED[0] += 1
                doc.saveAs("%s/%s-fail%d.FCStd" % (OUT, TAG, k))
        except Exception as e:
            rec["exc"] = "check %s: %s" % (type(e).__name__, e); rec["tb"] = traceback.format_exc().splitlines()[-3:]
            fails += 1; tally["check_exc"] += 1
            inc = None
        new_red = sorted(set(rec.get("errors") or []) - set(base_err))
        if kind == "delete" or (HEAL and inc is not None and new_red):
            if new_red:
                rec["red"] = new_red
            try:
                doc.undo(); doc.recompute()
                back = compare(signature(doc), before)
                rec["undo_back"] = back
                if back:
                    fails += 1; tally["undo_back_fail"] += 1
            except Exception as e:
                rec["undo_exc"] = "%s: %s" % (type(e).__name__, e); fails += 1
        elif committed:
            ncommit += 1
            if inc is None:
                try:
                    inc = signature(doc)
                except Exception:
                    inc = None
            if inc is not None:
                hist[committed] = inc; top = inc
                live = set(doc.UndoNames) | {"build"}
                hist = {n: h for n, h in hist.items() if n in live}
        if HEAL:
            base_err = signature(doc)["errors"]
        emit(**rec)
        if rec.get("fresh") in STOPAT:
            emit(step="stopat", at=k, verdict=rec["fresh"])
            break
        if STOP and k >= STOP:
            doc.saveAs("%s/%s-k%d.FCStd" % (OUT, TAG, k))
            break
    times.sort()
    summ = dict(seed=SEED, steps=STEPS, heal=HEAL, failures=fails, tally=dict(tally),
                inc_median=round(times[len(times) // 2], 3) if times else None,
                inc_max=round(times[-1], 3) if times else None, over_1s=sum(1 for t in times if t > 1.0))
    emit(step="summary", **summ)
    open("%s/%s.sum" % (OUT, TAG), "w").write(json.dumps(summ) + "\n")
    print("FUZZ", json.dumps(summ))


if os.environ.get("FUZZ_NOMAIN") != "1":   # FUZZ_NOMAIN=1: load only (reduceplus.py)
    try:
        main()
    except Exception:
        emit(step="fatal", tb=traceback.format_exc())
        print(traceback.format_exc())
