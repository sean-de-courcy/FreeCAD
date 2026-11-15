# fuzz.py: block F, scripted edit fuzz (ops#640, decision 435). Designed geometry only.
# A ~45-entry Part Studio (one part: plate, pockets, through-all holes, a Hole, bosses, revolve, groove, ribs,
# linear / polar / mirror patterns, fillets, chamfers) is edited by a seeded random sequence of in-range parameter
# changes and one-step reorders in the studio list. After each step the incremental result (doc.recompute() on the
# edited document) must equal a full recompute from scratch of the same document (saved, reopened, every object
# touched, recomputed): same faces/edges, volume to 1e-6, the same element names on the same faces, no exception.
# The incremental recompute's wall time is logged (decision 420: under 1 s typical).
#
# Run: FUZZ_SEED=<n> FUZZ_STEPS=<n> [FUZZ_HEAL=1] [FUZZ_OUT=<dir>] FreeCADCmd tools/fuzz/fuzz.py
#   (writes <FUZZ_OUT, default ./fuzz-out>/seed<n>.jsonl and .sum; FUZZ_HEAL=1 undoes a step that turns a feature red and checks
#   that the undo restores the part). See tools/fuzz/README.md.
# Replay a prefix: FUZZ_STOP=<k> stops after step k and saves the document as out/seed<n>-k<k>.FCStd.
import os, sys, json, math, random, time, traceback
import FreeCAD as App
import Part, Sketcher, PartDesign

V = App.Vector
OUT = os.environ.get("FUZZ_OUT", os.path.join(os.getcwd(), "fuzz-out"))
os.makedirs(OUT, exist_ok=True)
SEED = int(os.environ.get("FUZZ_SEED", "1"))
STEPS = int(os.environ.get("FUZZ_STEPS", "200"))
STOP = int(os.environ.get("FUZZ_STOP", "0"))
ONLY = os.environ.get("FUZZ_ONLY", "")          # comma list of step kinds to keep (reduction aid)
TAG = os.environ.get("FUZZ_TAG", "seed%d" % SEED)
LOG = open("%s/%s.jsonl" % (OUT, TAG), "w", buffering=1)


def emit(**kw):
    LOG.write(json.dumps(kw, default=str) + "\n")


# ------------------------------------------------------------------ sketch helpers (fully constrained)
def _lines(sk, x0, y0, x1, y1):
    pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    f = len(sk.Geometry)
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", f + i, 2, f + (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", f)); sk.addConstraint(Sketcher.Constraint("Horizontal", f + 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", f + 1)); sk.addConstraint(Sketcher.Constraint("Vertical", f + 3))
    return f


def named(sk, c, name):
    i = sk.addConstraint(c)
    sk.renameConstraint(i, name)
    return i


def crect(sk, tag, x, y, w, h):
    """A rectangle with its lower-left corner at (x, y), size w x h; constraints <tag>x <tag>y <tag>w <tag>h."""
    f = _lines(sk, x, y, x + w, y + h)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, f, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, f, 1, y), tag + "y")
    named(sk, Sketcher.Constraint("DistanceX", f, 1, f, 2, w), tag + "w")
    named(sk, Sketcher.Constraint("DistanceY", f + 1, 1, f + 1, 2, h), tag + "h")


def ccircle(sk, tag, x, y, r):
    g = sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 3, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 3, y), tag + "y")
    named(sk, Sketcher.Constraint("Radius", g, r), tag + "r")


def point(sk, tag, x, y):
    g = sk.addGeometry(Part.Point(V(x, y, 0)), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 1, y), tag + "y")


# ------------------------------------------------------------------ the designed studio
class Studio:
    def __init__(self, doc):
        self.doc = doc
        self.body = doc.addObject("PartDesign::Body", "Plate")
        self.o = self.body.Origin.OriginFeatures   # X_Axis Y_Axis Z_Axis XY XZ YZ
        self.params = []    # (object name, kind, key, lo, hi, integer)

    def sk(self, name, plane=3, z=None):
        s = self.body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(self.o[plane], "")]
        s.MapMode = "FlatFace"
        if z is not None:
            s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        PartDesign.studioInsert(s, -1)
        return s

    PATTERNS = ("LinearPattern", "PolarPattern", "Mirrored")

    def feat(self, kind, name, **props):
        if kind in self.PATTERNS:   # slice 8: made outside the Body, then added and listed (TestStudioList.insertPattern)
            f = self.doc.addObject("PartDesign::" + kind, name)
            for k, v in props.items():
                setattr(f, k, v)
            self.body.addObject(f)
        else:
            f = self.body.newObject("PartDesign::" + kind, name)
            for k, v in props.items():
                setattr(f, k, v)
        PartDesign.studioInsert(f, -1)
        self.doc.recompute()
        return f

    def p(self, obj, key, lo, hi, kind="datum", integer=False):
        self.params.append((obj.Name, kind, key, lo, hi, integer))

    def tipShape(self):
        return self.body.Tip.Shape

    def edgesWhere(self, feature, pred):
        sh = feature.Shape
        return ["Edge%d" % i for i, e in enumerate(sh.Edges, 1) if pred(e)]

    def build(self):
        doc, o = self.doc, self.o
        PartDesign.studioList(doc, True)
        # 1-2 base plate 120 x 80 x 10, centred
        s = self.sk("BaseSk"); crect(s, "B", -60, -40, 120, 80)
        self.p(s, "Bw", 110, 130); self.p(s, "Bh", 75, 90)
        base = self.feat("Pad", "Base", Profile=s, Length=10); self.p(base, "Length", 8, 14, "prop")
        # 3-4 corner pocket
        s = self.sk("Pk1Sk", z=20); crect(s, "P1", -52, -32, 20, 15)
        self.p(s, "P1x", -55, -45); self.p(s, "P1w", 14, 24); self.p(s, "P1h", 10, 18)
        pk1 = self.feat("Pocket", "Pocket1", Profile=s, Length=14); self.p(pk1, "Length", 12, 16, "prop")
        # 5-7 small pocket + linear pattern along X
        s = self.sk("Pk2Sk", z=20); crect(s, "P2", -18, -30, 10, 10)
        self.p(s, "P2x", -22, -14); self.p(s, "P2w", 6, 12)
        pk2 = self.feat("Pocket", "Pocket2", Profile=s, Length=13); self.p(pk2, "Length", 11.5, 15, "prop")
        lp = self.feat("LinearPattern", "LinPat", Originals=[pk2], Direction=(o[0], [""]), Length=40, Occurrences=3)
        self.p(lp, "Length", 30, 48, "prop"); self.p(lp, "Occurrences", 2, 4, "prop", True)
        # 8-10 through-all hole + polar pattern about Z
        s = self.sk("HoleSk"); ccircle(s, "H", 28, 4, 3)
        self.p(s, "Hx", 24, 32); self.p(s, "Hr", 2, 4)
        hole = self.feat("Pocket", "ThruHole", Profile=s, Type="ThroughAll", SideType="Symmetric")
        pp = self.feat("PolarPattern", "PolPat", Originals=[hole], Axis=(o[2], [""]), Angle=360, Occurrences=6)
        self.p(pp, "Occurrences", 3, 8, "prop", True)
        # 11-12 boss
        s = self.sk("BossSk", z=10); ccircle(s, "C", -35, 18, 8)
        self.p(s, "Cx", -40, -30); self.p(s, "Cy", 14, 22); self.p(s, "Cr", 5, 10)
        boss = self.feat("Pad", "Boss", Profile=s, Length=8); self.p(boss, "Length", 4, 12, "prop")
        # 13 mirror the boss about YZ
        mir = self.feat("Mirrored", "MirBoss", Originals=[boss], MirrorPlane=(o[5], [""]))
        # 14-15 revolved ring around Z (profile on XZ)
        s = self.sk("RingSk", plane=4); crect(s, "R", 42, 10, 5, 4)
        self.p(s, "Rx", 40, 46); self.p(s, "Rw", 3, 6); self.p(s, "Rh", 2, 6)
        ring = self.feat("Revolution", "Ring", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        # 16-17 groove around Z
        s = self.sk("GrooveSk", plane=4); crect(s, "G", 53, 6, 3, 3)
        self.p(s, "Gx", 52, 55); self.p(s, "Gy", 4, 7)
        groove = self.feat("Groove", "Groove", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        # 18-19 ribs (two pads) on top
        s = self.sk("RibSk", z=10); crect(s, "K1", -10, 20, 25, 3); crect(s, "K2", -10, 28, 25, 3)
        self.p(s, "K1w", 15, 30); self.p(s, "K2y", 26, 32)
        ribs = self.feat("Pad", "Ribs", Profile=s, Length=4); self.p(ribs, "Length", 2, 7, "prop")
        # 20 linear pattern of the ribs along -Y? along Y, 2 copies
        lp2 = self.feat("LinearPattern", "RibPat", Originals=[ribs], Direction=(o[1], [""]), Reversed=True, Length=40, Occurrences=2)
        self.p(lp2, "Length", 36, 46, "prop")
        # 21-22 a Hole feature (counterbore) on the top face
        s = self.sk("HoleFSk", z=10); point(s, "Q", -45, 30)
        self.p(s, "Qx", -50, -42); self.p(s, "Qy", 26, 33)
        hf = self.feat("Hole", "CBHole", Profile=s, Diameter=5, Depth=7, DepthType="Dimension",
                       HoleCutType="Counterbore", HoleCutDiameter=9, HoleCutDepth=2)
        self.p(hf, "Diameter", 3, 6, "prop"); self.p(hf, "Depth", 4, 9, "prop")
        pp2 = self.feat("PolarPattern", "CBPat", Originals=[hf], Axis=(o[2], [""]), Angle=360, Occurrences=4)
        self.p(pp2, "Occurrences", 2, 5, "prop", True)
        # 23-24 slot pocket across the plate front
        s = self.sk("SlotSk", z=20); crect(s, "S", 10, -38, 30, 4)
        self.p(s, "Sx", 5, 15); self.p(s, "Sw", 20, 34); self.p(s, "Sh", 3, 6)
        slot = self.feat("Pocket", "Slot", Profile=s, Length=12); self.p(slot, "Length", 11, 14, "prop")
        self.feat("Mirrored", "MirSlot", Originals=[slot], MirrorPlane=(o[4], [""]))
        # 25-26 a second boss (square) and its chamfer later
        s = self.sk("Boss2Sk", z=10); crect(s, "D", 14, -12, 10, 10)
        self.p(s, "Dx", 12, 16); self.p(s, "Dw", 7, 10)
        boss2 = self.feat("Pad", "Boss2", Profile=s, Length=6); self.p(boss2, "Length", 3, 10, "prop")
        doc.recompute()
        sh = boss2.Shape
        sides = ["Face%d" % i for i, f in enumerate(sh.Faces, 1)
                 if abs(f.normalAt(0, 0).z) < 1e-6 and 10 < f.CenterOfMass.x < 30 and -15 < f.CenterOfMass.y < 1 and f.CenterOfMass.z > 10]
        topf = ["Face%d" % i for i, f in enumerate(sh.Faces, 1)
                if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 16) < 1e-6 and 10 < f.CenterOfMass.x < 30]
        dr = self.feat("Draft", "Boss2Draft", Base=(boss2, sides), NeutralPlane=(boss2, topf[:1]), Angle=3)
        self.p(dr, "Angle", 1, 6, "prop")
        doc.recompute()
        # 27 fillet: the plate's four vertical outer edges (picked on Base)
        bw = 60
        vert = self.edgesWhere(base, lambda e: abs(e.Vertexes[0].Point.z - e.Vertexes[-1].Point.z) > 5
                               and abs(abs(e.Vertexes[0].Point.x) - bw) < 1e-6 and abs(abs(e.Vertexes[0].Point.y) - 40) < 1e-6)
        last = self.body.Tip
        f1 = self.feat("Fillet", "CornerFillet", Base=(last, self.mapEdges(base, last, vert)), Radius=4)
        self.p(f1, "Radius", 2, 6, "prop")
        doc.recompute()
        # 28 chamfer: the top edges of Boss2
        top = self.edgesWhere(boss2, lambda e: all(abs(v.Point.z - 16) < 1e-6 for v in e.Vertexes)
                              and all(v.Point.x > 10 and v.Point.y < 0 for v in e.Vertexes))
        last = self.body.Tip
        c1 = self.feat("Chamfer", "Boss2Chamfer", Base=(last, self.mapEdges(boss2, last, top)), Size=1)
        self.p(c1, "Size", 0.5, 2, "prop")
        doc.recompute()
        # 29 fillet: the top rim of the boss (circle at z 18)
        rim = self.edgesWhere(boss, lambda e: hasattr(e.Curve, "Radius") and all(abs(v.Point.z - 18) < 1e-6 for v in e.Vertexes)
                              and e.Vertexes[0].Point.x < 0)
        last = self.body.Tip
        f2 = self.feat("Fillet", "BossFillet", Base=(last, self.mapEdges(boss, last, rim)), Radius=1.5)
        self.p(f2, "Radius", 0.5, 3, "prop")
        doc.recompute()
        # 30 chamfer: the top edges of Pocket1's rim
        rim1 = self.edgesWhere(pk1, lambda e: all(abs(v.Point.z - 10) < 1e-6 for v in e.Vertexes)
                               and all(v.Point.x < -25 and v.Point.y < -10 for v in e.Vertexes))
        last = self.body.Tip
        c2 = self.feat("Chamfer", "Pk1Chamfer", Base=(last, self.mapEdges(pk1, last, rim1)), Size=0.8)
        self.p(c2, "Size", 0.3, 1.5, "prop")
        doc.recompute()
        # 31-33 a late pocket that cuts through the fillets' region and a polar pattern of it
        s = self.sk("LateSk", z=20); crect(s, "L", -6, -6, 12, 12)
        self.p(s, "Lw", 6, 16); self.p(s, "Lx", -8, -4)
        late = self.feat("Pocket", "LatePocket", Profile=s, Length=12); self.p(late, "Length", 11, 14, "prop")
        doc.recompute()
        s = self.sk("BackSk", z=20); crect(s, "E", -30, 34, 24, 4)
        self.p(s, "Ex", -34, -26); self.p(s, "Ew", 16, 28)
        back = self.feat("Pocket", "BackSlot", Profile=s, Length=12.5); self.p(back, "Length", 11, 14, "prop")
        s = self.sk("TabSk", z=10); crect(s, "T", -58, -10, 8, 20)
        self.p(s, "Ty", -14, -6); self.p(s, "Th", 12, 24)
        tab = self.feat("Pad", "Tab", Profile=s, Length=5); self.p(tab, "Length", 2, 9, "prop")
        edges = self.edgesWhere(tab, lambda e: all(abs(v.Point.z - 15) < 1e-6 and v.Point.x < -49 for v in e.Vertexes))
        last = self.body.Tip
        c3 = self.feat("Chamfer", "TabChamfer", Base=(last, self.mapEdges(tab, last, edges)), Size=0.6)
        self.p(c3, "Size", 0.3, 1.2, "prop")
        self.features = [x for x in self.body.Group if x.isDerivedFrom("PartDesign::Feature")]
        return self

    def mapEdges(self, src, last, names):
        """src's edges named, as edges of last's shape (same geometry: centre of mass)."""
        out = []
        sh = last.Shape
        for n in names:
            c = src.Shape.getElement(n).CenterOfMass
            for i, e in enumerate(sh.Edges, 1):
                if (e.CenterOfMass - c).Length < 1e-6:
                    out.append("Edge%d" % i); break
        return out


# ------------------------------------------------------------------ state signature
def signature(doc):
    body = doc.getObject("Plate")
    out = {}
    sh = body.Shape
    out["null"] = sh.isNull()
    if not sh.isNull():
        out.update(valid=sh.isValid(), solids=len(sh.Solids), faces=len(sh.Faces), edges=len(sh.Edges),
                   vol=sh.Volume, area=sh.Area)
        names = {}
        try:
            em = sh.ElementReverseMap   # indexed -> mapped (or list of mapped)
        except Exception:
            em = None
        if em is None:
            em = {}
            for k, v in sh.ElementMap.items():
                em.setdefault(v, k)
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
        diffs.append("names: %d only incremental, %d only full, %d on other faces; e.g. inc %s full %s moved %s"
                     % (len(only_a), len(only_b), len(moved), only_a[:2], only_b[:2], moved[:2]))
    for n in sorted(set(a["features"]) | set(b["features"])):
        if a["features"].get(n) != b["features"].get(n):
            diffs.append("feature %s %s != %s" % (n, a["features"].get(n), b["features"].get(n)))
    if a["errors"] != b["errors"]:
        diffs.append("errors %s != %s" % (a["errors"], b["errors"]))
    if a.get("warnings") != b.get("warnings"):
        diffs.append("warnings %s != %s" % (a.get("warnings"), b.get("warnings")))
    return diffs


def fullFrom(doc, step):
    import shutil
    path = "%s/%s-cur.FCStd" % (OUT, TAG)
    copy = "%s/%s-full.FCStd" % (OUT, TAG)
    doc.saveAs(path)
    shutil.copyfile(path, copy)
    d2 = App.openDocument(copy)
    assert d2.Name != doc.Name
    try:
        for o in d2.Objects:
            o.touch()
        t0 = time.perf_counter(); d2.recompute(); t = time.perf_counter() - t0
        return signature(d2), t
    finally:
        App.closeDocument(d2.Name)


# ------------------------------------------------------------------ edit steps
def datumKey(sk, name):
    for i, c in enumerate(sk.Constraints):
        if c.Name == name:
            return i
    raise KeyError(name)


UNDO = [None]
HEAL = os.environ.get("FUZZ_HEAL") == "1"   # revert a step that turns a feature red (keeps the model healthy)


def stepParam(doc, rng, params):
    name, kind, key, lo, hi, integer = rng.choice(params)
    obj = doc.getObject(name)
    if integer:
        v = rng.randint(int(lo), int(hi))
    else:
        v = round(rng.uniform(lo, hi), 2)
    if kind == "datum":
        i = datumKey(obj, key); old = obj.Constraints[i].Value
        obj.setDatum(i, App.Units.Quantity("%s mm" % v))
        UNDO[0] = lambda: obj.setDatum(i, App.Units.Quantity("%s mm" % old))
    else:
        old = getattr(obj, key)
        setattr(obj, key, v)
        UNDO[0] = lambda: setattr(obj, key, old)
    return "%s.%s = %s" % (name, key, v)


def stepMove(doc, rng):
    lst = PartDesign.studioList(doc)
    entries = list(lst.Entries)
    movable = [e for e in entries if e.isDerivedFrom("PartDesign::Feature") or e.isDerivedFrom("Sketcher::SketchObject")]
    e = rng.choice(movable)
    i = entries.index(e)
    j = i + rng.choice((-1, 1))
    if j < 0 or j >= len(entries):
        j = i - (j - i)
    try:
        PartDesign.studioMove(e, j)
    except ValueError as x:   # the studio refuses a move against a dependency: a user sees the message
        return "move %s %d -> %d refused: %s" % (e.Name, i, j, x)
    UNDO[0] = lambda: PartDesign.studioMove(e, i)
    after = [x.Name for x in PartDesign.studioList(doc).Entries]
    return "move %s %d -> %d%s" % (e.Name, i, j, "" if after.index(e.Name) == j else " (refused: at %d)" % after.index(e.Name))


def main():
    rng = random.Random(SEED)
    doc = App.newDocument("Fuzz")
    t0 = time.perf_counter()
    st = Studio(doc).build()
    PartDesign.studioList(doc, True)
    doc.recompute()
    sig0 = signature(doc)
    emit(step=0, what="build", wall_s=round(time.perf_counter() - t0, 3), sig={k: sig0.get(k) for k in ("valid", "solids", "faces", "edges", "vol", "named")},
         errors=sig0["errors"], list=sig0["list"], nfeat=len(st.features), nlist=len(sig0["list"] or []))
    full0, tf = fullFrom(doc, 0)
    d0 = compare(sig0, full0)
    emit(step=0, what="build vs full", diffs=d0, full_s=round(tf, 3))
    kinds = ONLY.split(",") if ONLY else None
    fails = 0; times = []; base_err = sig0["errors"]
    for k in range(1, STEPS + 1):
        kind = "move" if rng.random() < 0.25 else "param"
        # draw both choices to keep the stream identical whatever FUZZ_ONLY keeps
        r2 = random.Random(rng.random())
        if kinds and kind not in kinds:
            continue
        rec = dict(step=k, kind=kind)
        before = signature(doc) if HEAL else None
        try:
            what = stepMove(doc, r2) if kind == "move" else stepParam(doc, r2, st.params)
            rec["what"] = what
            t0 = time.perf_counter(); doc.recompute(); dt = time.perf_counter() - t0
            rec["inc_s"] = round(dt, 3); times.append(dt)
        except Exception as e:
            rec["exc"] = "%s: %s" % (type(e).__name__, e); rec["tb"] = traceback.format_exc().splitlines()[-3:]
            fails += 1
            emit(**rec)
            if STOP and k >= STOP:
                break
            continue
        try:
            inc = signature(doc)
            full, tf = fullFrom(doc, k)
            diffs = compare(inc, full)
            rec.update(full_s=round(tf, 3), vol=inc.get("vol"), faces=inc.get("faces"), named=inc.get("named"), warnings=inc.get("warnings"), errors=inc["errors"], diffs=diffs)
            if diffs:
                fails += 1
                doc.saveAs("%s/%s-fail%d.FCStd" % (OUT, TAG, k))   # the incremental state, for reduction
        except Exception as e:
            rec["exc"] = "check %s: %s" % (type(e).__name__, e); rec["tb"] = traceback.format_exc().splitlines()[-3:]
            fails += 1
        if HEAL and not rec.get("exc") and set(rec.get("errors") or []) - set(base_err):
            rec["red"] = sorted(set(rec["errors"]) - set(base_err))
            try:
                UNDO[0](); doc.recompute()
                inc = signature(doc); full, tf = fullFrom(doc, k)
                d2 = compare(inc, full)
                rec["revert_errors"] = inc["errors"]; rec["revert_diffs"] = d2
                back = compare(inc, before)
                if back:
                    rec["revert_vs_before"] = back
                if d2:
                    fails += 1
                if set(inc["errors"]) - set(base_err):
                    rec["revert_stuck"] = True
            except Exception as e:
                rec["revert_exc"] = "%s: %s" % (type(e).__name__, e); fails += 1
        base_err = signature(doc)["errors"] if HEAL else base_err
        emit(**rec)
        if STOP and k >= STOP:
            doc.saveAs("%s/%s-k%d.FCStd" % (OUT, TAG, k))
            break
    times.sort()
    summ = dict(seed=SEED, steps=STEPS, failures=fails,
                inc_median=round(times[len(times) // 2], 3) if times else None,
                inc_p90=round(times[int(len(times) * 0.9)], 3) if times else None,
                inc_max=round(times[-1], 3) if times else None,
                over_1s=sum(1 for t in times if t > 1.0))
    emit(step="summary", **summ)
    open("%s/%s.sum" % (OUT, TAG), "w").write(json.dumps(summ) + "\n")
    print("FUZZ", json.dumps(summ))


try:
    main()
except Exception:
    emit(step="fatal", tb=traceback.format_exc())
    print(traceback.format_exc())
