# truth.py: A-cut truth walk (ops#640, robustness sweep rank 2). Designed geometry only.
# Each template is a small Part Studio whose volume and area are closed-form in its parameters. A seeded walk edits
# the parameters in the live document (draws reach up to and past the formula's limits) and after every step
# compares the result with the formula:
#   OK      V within 1e-6 and A within 1e-5 (relative) of the formula, valid single solid, no red feature;
#   SILENT  a valid result with no error whose V or A is off the formula (the target);
#   LOUD    an error, an invalid or empty shape, while the formula is defined;
#   BEYOND  the parameters are within EPS of a case boundary or past the formula's limit: the row goes to the
#           Onshape queue (R3), with what FreeCAD did;
#   WARN    the face count by surface type differs from the first OK state of the same regime (counts only warn);
#   REWRITE FreeCAD changed a parameter the walk set (read back after every step); the walk then follows the document.
# Every 25 steps the document is saved, reopened and recomputed, and V must not change.
#
# Templates: T1 plate (through pocket, boss, through hole, countersink Hole); T2 linear pattern of blind or through
# pockets and a polar pattern of through holes; T3 boss + Mirrored (union, the lens when the copies overlap);
# T5f / T5c fillet / chamfer on a box's 12 or 4 vertical edges (sphere octants / 5/6 r^3 corner facets).
# Run: TRUTH_T=T1|T2|T3|T5f|T5c TRUTH_SEED=<n> TRUTH_STEPS=<n> [TRUTH_OUT=<dir>] FreeCADCmd tools/fuzz/truth.py
#   writes <out>/<T>-<seed>.jsonl and .sum; TRUTH_SPEC=1 writes <out>/<T>.spec.json (the template for the oracle).
import os, json, math, random, time, traceback
from collections import Counter
import FreeCAD as App
import Part, Sketcher, PartDesign

V = App.Vector
PI = math.pi
OUT = os.environ.get("TRUTH_OUT", os.path.join(os.getcwd(), "truth-out"))
os.makedirs(OUT, exist_ok=True)
T = os.environ.get("TRUTH_T", "T1")
SEED = int(os.environ.get("TRUTH_SEED", "1"))
STEPS = int(os.environ.get("TRUTH_STEPS", "200"))
TAG = "%s-%d" % (T, SEED)
EPS = 1e-3          # mm: a margin this close to a case boundary is BEYOND, not SILENT
LOG = open("%s/%s.jsonl" % (OUT, TAG), "w", buffering=1)


def emit(**kw):
    LOG.write(json.dumps(kw, default=str) + "\n")


# ------------------------------------------------------------------ sketch helpers (fully constrained, named)
def named(sk, c, name):
    sk.renameConstraint(sk.addConstraint(c), name)


def rect(sk, tag, x, y, w, h):
    f = len(sk.Geometry)
    pts = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", f + i, 2, f + (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", f)); sk.addConstraint(Sketcher.Constraint("Horizontal", f + 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", f + 1)); sk.addConstraint(Sketcher.Constraint("Vertical", f + 3))
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, f, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, f, 1, y), tag + "y")
    named(sk, Sketcher.Constraint("DistanceX", f, 1, f, 2, w), tag + "w")
    named(sk, Sketcher.Constraint("DistanceY", f + 1, 1, f + 1, 2, h), tag + "h")


def circle(sk, tag, x, y, r):
    g = sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 3, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 3, y), tag + "y")
    named(sk, Sketcher.Constraint("Radius", g, r), tag + "r")


def point(sk, tag, x, y):
    g = sk.addGeometry(Part.Point(V(x, y, 0)), False)
    named(sk, Sketcher.Constraint("DistanceX", -1, 1, g, 1, x), tag + "x")
    named(sk, Sketcher.Constraint("DistanceY", -1, 1, g, 1, y), tag + "y")


class Builder:
    PATTERNS = ("LinearPattern", "PolarPattern", "Mirrored")

    def __init__(self, doc):
        self.doc = doc
        self.body = doc.addObject("PartDesign::Body", "Part")
        self.o = self.body.Origin.OriginFeatures
        PartDesign.studioList(doc, True)

    def sk(self, name, z=None):
        s = self.body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(self.o[3], "")]
        s.MapMode = "FlatFace"
        if z is not None:
            s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        PartDesign.studioInsert(s, -1)
        return s

    def feat(self, kind, name, **props):
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


# ------------------------------------------------------------------ geometry helpers for margins
def circRectGap(cx, cy, r, x0, y0, x1, y1):
    dx = max(x0 - cx, 0, cx - x1); dy = max(y0 - cy, 0, cy - y1)
    return math.hypot(dx, dy) - r


def circInRect(cx, cy, r, x0, y0, x1, y1):
    return min(cx - r - x0, x1 - cx - r, cy - r - y0, y1 - cy - r)


# ------------------------------------------------------------------ templates
# A template: P (defaults), R (draw ranges, reaching past the limits), where (param -> ("datum", sketch, constraint)
# | ("prop", feature, property)), build(b, p), truth(p) -> (vol, area, margin, regime).
class T1:
    """plate a x b x t; through-all rectangular pocket; cylinder boss on top; through hole; countersink Hole (90 deg)"""
    P = dict(a=100, b=60, t=8, px=10, py=10, pw=20, ph=15, bx=50, by=40, rb=8, hb=10, hx=80, hy=15, rh=4,
             kx=80, ky=45, d=5, D=10)
    R = dict(t=(4, 14), pw=(5, 45), ph=(5, 35), bx=(20, 95), rb=(3, 21), hb=(2, 20), rh=(1, 17), d=(2, 9), D=(6, 22))
    where = dict(a=("datum", "PlateSk", "Aw"), b=("datum", "PlateSk", "Ah"), t=("prop", "Plate", "Length"),
                 pw=("datum", "PocketSk", "Pw"), ph=("datum", "PocketSk", "Ph"), bx=("datum", "BossSk", "Bx"),
                 rb=("datum", "BossSk", "Br"), hb=("prop", "Boss", "Length"), rh=("datum", "HoleSk", "Hr"),
                 d=("prop", "CSink", "Diameter"), D=("prop", "CSink", "HoleCutDiameter"))

    @staticmethod
    def build(b, p):
        s = b.sk("PlateSk"); rect(s, "A", 0, 0, p["a"], p["b"])
        plate = b.feat("Pad", "Plate", Profile=s, Length=p["t"])
        s = b.sk("PocketSk", z=p["t"]); rect(s, "P", p["px"], p["py"], p["pw"], p["ph"])
        b.feat("Pocket", "ThruPocket", Profile=s, Type="ThroughAll")
        s = b.sk("BossSk", z=p["t"]); circle(s, "B", p["bx"], p["by"], p["rb"])
        b.feat("Pad", "Boss", Profile=s, Length=p["hb"])
        s = b.sk("HoleSk", z=p["t"]); circle(s, "H", p["hx"], p["hy"], p["rh"])
        b.feat("Pocket", "ThruHole", Profile=s, Type="ThroughAll")
        s = b.sk("CSinkSk", z=p["t"]); point(s, "K", p["kx"], p["ky"])
        b.feat("Hole", "CSink", Profile=s, Diameter=p["d"], DepthType="ThroughAll", HoleCutType="Countersink",
               HoleCutDiameter=p["D"], HoleCutCountersinkAngle=90)
        return plate

    @staticmethod
    def truth(p):
        a, b, t = p["a"], p["b"], p["t"]
        r, R = p["d"] / 2, p["D"] / 2
        hc = R - r                     # 90 deg countersink depth
        m = [min(p["px"], p["py"], a - p["px"] - p["pw"], b - p["py"] - p["ph"])]
        rx = (p["px"], p["py"], p["px"] + p["pw"], p["py"] + p["ph"])
        cs = [(p["bx"], p["by"], p["rb"]), (p["hx"], p["hy"], p["rh"]), (p["kx"], p["ky"], R)]
        for (cx, cy, cr) in cs:
            m.append(circInRect(cx, cy, cr, 0, 0, a, b))
            m.append(circRectGap(cx, cy, cr, *rx))
        for i in range(3):
            for j in range(i + 1, 3):
                m.append(math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1]) - cs[i][2] - cs[j][2])
        m.append(t - hc)               # the cone stays inside the plate
        m.append(R - r)                # a countersink, not a counterbore
        vol = (a * b * t - p["pw"] * p["ph"] * t + PI * p["rb"] ** 2 * p["hb"] - PI * p["rh"] ** 2 * t
               - PI * r * r * t - (PI * hc / 3 * (R * R + R * r + r * r) - PI * r * r * hc))
        area = (2 * a * b + 2 * (a + b) * t - 2 * p["pw"] * p["ph"] + 2 * (p["pw"] + p["ph"]) * t
                + 2 * PI * p["rb"] * p["hb"] - 2 * PI * p["rh"] ** 2 + 2 * PI * p["rh"] * t
                - PI * r * r - PI * R * R + 2 * PI * r * (t - hc) + PI * (R + r) * hc * math.sqrt(2))
        return vol, area, min(m), "one"


class T2:
    """plate centred, a x b x t; a row of m blind (or through) pockets w x h deep d, first at (x0, y0), the last L further
    along X; n through holes of radius rh at radius R about Z"""
    P = dict(a=120, b=80, t=10, x0=-50, y0=-37, w=12, h=8, d=4, m=4, L=80, R=18, rh=3, n=6)
    R = dict(w=(5, 35), L=(20, 112), m=(2, 7), d=(1, 16), R=(2, 30), rh=(1, 10), n=(2, 14), t=(6, 14))
    where = dict(a=("datum", "PlateSk", "Aw"), b=("datum", "PlateSk", "Ah"), t=("prop", "Plate", "Length"),
                 w=("datum", "RowSk", "Pw"), d=("prop", "RowPocket", "Length"), m=("prop", "RowPat", "Occurrences"),
                 L=("prop", "RowPat", "Length"), R=("datum", "HoleSk", "Hx"), rh=("datum", "HoleSk", "Hr"),
                 n=("prop", "HolePat", "Occurrences"))
    INT = ("m", "n")
    CENTRED = True

    @staticmethod
    def build(b, p):
        o = b.o
        s = b.sk("PlateSk"); rect(s, "A", -p["a"] / 2, -p["b"] / 2, p["a"], p["b"])
        plate = b.feat("Pad", "Plate", Profile=s, Length=p["t"])
        s = b.sk("RowSk", z=p["t"]); rect(s, "P", p["x0"], p["y0"], p["w"], p["h"])
        pk = b.feat("Pocket", "RowPocket", Profile=s, Length=p["d"])
        b.feat("LinearPattern", "RowPat", Originals=[pk], Direction=(o[0], [""]), Length=p["L"], Occurrences=p["m"])
        s = b.sk("HoleSk", z=p["t"]); circle(s, "H", p["R"], 0, p["rh"])
        hole = b.feat("Pocket", "Hole", Profile=s, Type="ThroughAll")
        b.feat("PolarPattern", "HolePat", Originals=[hole], Axis=(o[2], [""]), Angle=360, Occurrences=p["n"])
        return plate

    @staticmethod
    def truth(p):
        a, b, t, w, h, d, m, L = p["a"], p["b"], p["t"], p["w"], p["h"], p["d"], int(p["m"]), p["L"]
        s = L / (m - 1)
        x0, y0 = p["x0"], p["y0"]
        contiguous = s < w
        Lu = (m - 1) * s + w if contiguous else m * w
        mar = [x0 + a / 2, y0 + b / 2, a / 2 - (x0 + L + w), b / 2 - (y0 + h), abs(s - w), abs(d - t)]
        n, R, rh = int(p["n"]), p["R"], p["rh"]
        mar.append(b / 2 - R - rh); mar.append(a / 2 - R - rh)
        if n > 1:
            mar.append(2 * R * math.sin(PI / n) - 2 * rh)
        for k in range(n):
            th = 2 * PI * k / n
            mar.append(circRectGap(R * math.cos(th), R * math.sin(th), rh, x0, y0, x0 + L + w, y0 + h))
        dd = min(d, t)
        nrect = 1 if contiguous else m
        perim = 2 * (Lu + h) if contiguous else m * 2 * (w + h)
        vol = a * b * t - Lu * h * dd - n * PI * rh * rh * t
        area = 2 * a * b + 2 * (a + b) * t + perim * dd - (2 * Lu * h if d >= t else 0)
        area += n * (-2 * PI * rh * rh + 2 * PI * rh * t)
        regime = "%s-%s-m%d-n%d" % ("row" if contiguous else "sep", "thru" if d >= t else "blind", m, n)
        return vol, area, min(mar), regime


def lens(r, dist):
    """area and the arc length of one circle inside the other, for two circles of radius r at centre distance dist"""
    if dist >= 2 * r:
        return 0.0, 0.0
    al = math.acos(dist / (2 * r))
    return 2 * r * r * al - dist / 2 * math.sqrt(4 * r * r - dist * dist), 2 * r * al


class T3:
    """box a x b x t centred; cylinder boss r x h at (cx, cy) on top; Mirrored about YZ (union; a lens when they overlap)"""
    P = dict(a=100, b=60, t=8, cx=25, cy=0, r=10, h=12)
    R = dict(cx=(-6, 46), cy=(-32, 32), r=(2, 30), h=(1, 20), a=(40, 120), t=(3, 14))
    where = dict(a=("datum", "PlateSk", "Aw"), t=("prop", "Plate", "Length"), cx=("datum", "BossSk", "Bx"),
                 cy=("datum", "BossSk", "By"), r=("datum", "BossSk", "Br"), h=("prop", "Boss", "Length"))
    CENTRED = True

    @staticmethod
    def build(b, p):
        o = b.o
        s = b.sk("PlateSk"); rect(s, "A", -p["a"] / 2, -p["b"] / 2, p["a"], p["b"])
        plate = b.feat("Pad", "Plate", Profile=s, Length=p["t"])
        s = b.sk("BossSk", z=p["t"]); circle(s, "B", p["cx"], p["cy"], p["r"])
        boss = b.feat("Pad", "Boss", Profile=s, Length=p["h"])
        b.feat("Mirrored", "MirBoss", Originals=[boss], MirrorPlane=(o[5], [""]))
        return plate

    @staticmethod
    def truth(p):
        a, b, t, cx, cy, r, h = p["a"], p["b"], p["t"], abs(p["cx"]), p["cy"], p["r"], p["h"]
        dist = 2 * cx
        la, arc = lens(r, dist)
        au = 2 * PI * r * r - la
        pu = 2 * (2 * PI * r - arc)
        mar = [a / 2 - cx - r, b / 2 - abs(cy) - r, abs(dist - 2 * r), dist]
        vol = a * b * t + au * h
        area = 2 * a * b + 2 * (a + b) * t + pu * h
        return vol, area, min(mar), "lens" if dist < 2 * r else "apart"


class T5:
    """box a x b x c; an equal fillet (T5f) or chamfer (T5c) of size r on all 12 edges or on the 4 vertical edges"""
    P = dict(a=40, b=30, c=20, r=3, all=1)
    R = dict(a=(10, 60), b=(10, 50), c=(6, 40), r=(0.5, 16), all=(0, 1))
    where = dict(a=("datum", "BoxSk", "Aw"), b=("datum", "BoxSk", "Ah"), c=("prop", "Box", "Length"),
                 r=("prop", "Dress", None), all=("edges", "Dress", None))
    INT = ("all",)
    KIND = "Fillet"

    @classmethod
    def build(cls, b, p):
        s = b.sk("BoxSk"); rect(s, "A", 0, 0, p["a"], p["b"])
        box = b.feat("Pad", "Box", Profile=s, Length=p["c"])
        key = "Radius" if cls.KIND == "Fillet" else "Size"
        b.feat(cls.KIND, "Dress", Base=(box, edgeSet(box, p["all"])), **{key: p["r"]})
        return box

    @classmethod
    def truth(cls, p):
        a, b, c, r = p["a"], p["b"], p["c"], p["r"]
        allE = int(p["all"]) == 1
        lim = min(a, b, c) / 2 if allE else min(a, b) / 2
        mar = lim - r
        if cls.KIND == "Fillet":
            if allE:
                se = (a - 2 * r) + (b - 2 * r) + (c - 2 * r)
                vol = a * b * c - (1 - PI / 4) * r * r * 4 * se - 8 * (r ** 3 - PI * r ** 3 / 6)
                area = (2 * ((a - 2 * r) * (b - 2 * r) + (a - 2 * r) * (c - 2 * r) + (b - 2 * r) * (c - 2 * r))
                        + 4 * se * PI * r / 2 + 4 * PI * r * r)
            else:
                vol = a * b * c - 4 * (1 - PI / 4) * r * r * c
                area = 2 * (a * b - 4 * (1 - PI / 4) * r * r) + 2 * (a - 2 * r) * c + 2 * (b - 2 * r) * c + 4 * PI * r / 2 * c
        else:
            if allE:
                se = (a - 2 * r) + (b - 2 * r) + (c - 2 * r)
                vol = a * b * c - 2 * r * r * se - 8 * (5.0 / 6) * r ** 3
                area = (2 * ((a - 2 * r) * (b - 2 * r) + (a - 2 * r) * (c - 2 * r) + (b - 2 * r) * (c - 2 * r))
                        + 4 * se * r * math.sqrt(2) + 8 * (math.sqrt(3) / 2) * r * r)
            else:
                vol = a * b * c - 4 * (r * r / 2) * c
                area = 2 * (a * b - 2 * r * r) + 2 * (a - 2 * r) * c + 2 * (b - 2 * r) * c + 4 * r * math.sqrt(2) * c
        return vol, area, mar, "all" if allE else "vert"


class T5f(T5):
    KIND = "Fillet"


class T5c(T5):
    KIND = "Chamfer"


def edgeSet(box, allE):
    sh = box.Shape
    if int(allE) == 1:
        return ["Edge%d" % i for i in range(1, len(sh.Edges) + 1)]
    return ["Edge%d" % i for i, e in enumerate(sh.Edges, 1) if abs(e.Vertexes[0].Point.z - e.Vertexes[-1].Point.z) > 1e-6]


TEMPLATES = dict(T1=T1, T2=T2, T3=T3, T5f=T5f, T5c=T5c)


# ------------------------------------------------------------------ live edits
def datum(sk, name, v):
    for i, c in enumerate(sk.Constraints):
        if c.Name == name:
            sk.setDatum(i, App.Units.Quantity("%s mm" % v))
            return
    raise KeyError(name)


def apply(doc, tpl, key, v):
    how, obj, prop = tpl.where[key]
    o = doc.getObject(obj)
    if how == "datum":
        if getattr(tpl, "CENTRED", False) and key in ("a", "b"):   # a centred plate stays centred (one edit, both datums)
            datum(o, prop, v)
            datum(o, "Ax" if key == "a" else "Ay", -v / 2.0)
        else:
            datum(o, prop, v)
    elif how == "edges":
        o.Base = (doc.getObject("Box"), edgeSet(doc.getObject("Box"), v))
    else:
        if prop is None:
            prop = "Radius" if hasattr(o, "Radius") else "Size"
        old = float(getattr(getattr(o, prop), "Value", getattr(o, prop)))
        setattr(o, prop, v)
        if key == "t":   # the sketches on the plate's top follow it (one edit, as a variable driving both)
            for s in doc.Objects:
                if s.isDerivedFrom("Sketcher::SketchObject") and abs(s.AttachmentOffset.Base.z - old) < 1e-9 and old > 0:
                    s.AttachmentOffset = App.Placement(V(0, 0, v), App.Rotation())


def readBack(doc, tpl, p):
    """parameters whose value in the document differs from what the walk set (FreeCAD rewrote a user value)"""
    out = {}
    for key, (how, obj, prop) in tpl.where.items():
        o = doc.getObject(obj)
        if how == "datum":
            x = [c.Value for c in o.Constraints if c.Name == prop][0]
        elif how == "edges":
            continue
        else:
            if prop is None:
                prop = "Radius" if hasattr(o, "Radius") else "Size"
            x = getattr(o, prop); x = float(getattr(x, "Value", x))
        if abs(x - float(p[key])) > 1e-9:
            out[key] = (p[key], round(x, 6))
    return out


def measure(doc):
    body = doc.getObject("Part")
    sh = body.Shape
    red = sorted(o.Name for o in doc.Objects if "Invalid" in o.State or "Error" in o.State)
    if sh.isNull():
        return dict(null=True, red=red)
    return dict(null=False, valid=sh.isValid(), solids=len(sh.Solids), vol=sh.Volume, area=sh.Area, faces=len(sh.Faces),
                ftypes=dict(Counter(type(f.Surface).__name__ for f in sh.Faces)), red=red)


def verdict(m, tr, seen):
    vol, area, mar, regime = tr
    rec = dict(f_vol=round(vol, 6), f_area=round(area, 6), margin=round(mar, 6), regime=regime)
    if mar < -EPS:
        rec["v"] = "BEYOND"; rec["why"] = "past the limit"
    elif abs(mar) <= EPS:
        rec["v"] = "BEYOND"; rec["why"] = "at a case boundary"
    elif m["null"] or m["red"] or not m["valid"] or m["solids"] != 1:
        rec["v"] = "LOUD"
    else:
        dv = abs(m["vol"] - vol) / max(1.0, abs(vol)); da = abs(m["area"] - area) / max(1.0, abs(area))
        rec.update(dv=float("%.3g" % dv), da=float("%.3g" % da))
        if dv > 1e-6 or da > 1e-5:
            rec["v"] = "SILENT"
        else:
            rec["v"] = "OK"
            first = seen.setdefault(regime, m["ftypes"])
            if first != m["ftypes"]:
                rec["v"] = "WARN"; rec["ftypes_first"] = first
    return rec


def reopenVol(doc):
    import shutil
    path = "%s/%s-cur.FCStd" % (OUT, TAG); copy = "%s/%s-re.FCStd" % (OUT, TAG)
    doc.saveAs(path); shutil.copyfile(path, copy)
    d2 = App.openDocument(copy)
    try:
        for o in d2.Objects:
            o.touch()
        d2.recompute()
        sh = d2.getObject("Part").Shape
        return None if sh.isNull() else sh.Volume
    finally:
        App.closeDocument(d2.Name)


def spec(tpl):
    """the template for the oracle: parameters, ranges, and the features in order with where each parameter lives"""
    return dict(template=T, doc=tpl.__doc__, defaults=tpl.P, ranges=tpl.R,
                params={k: list(x) for k, x in tpl.where.items()}, boundary_eps_mm=EPS)


def main():
    tpl = TEMPLATES[T]
    if os.environ.get("TRUTH_SPEC") == "1":
        json.dump(spec(tpl), open("%s/%s.spec.json" % (OUT, T), "w"), indent=1)
    rng = random.Random(SEED)
    doc = App.newDocument("Truth")
    p = dict(tpl.P)
    t0 = time.perf_counter()
    tpl.build(Builder(doc), p)
    doc.recompute()
    seen = {}
    m = measure(doc)
    rec = dict(step=0, p=dict(p), wall_s=round(time.perf_counter() - t0, 3), vol=m.get("vol"), area=m.get("area"), red=m["red"])
    rec.update(verdict(m, tpl.truth(p), seen))
    emit(**rec)
    tally = Counter([rec["v"]])
    ints = getattr(tpl, "INT", ())
    keys = sorted(tpl.R)
    past = False
    for k in range(1, STEPS + 1):
        key = rng.choice(keys)
        lo, hi = tpl.R[key]
        v = rng.randint(lo, hi) if key in ints else round(rng.uniform(lo, hi), 2)
        if past and rng.random() < 0.5:   # pull back: past a limit, half the steps reset one changed parameter
            changed = [x for x in keys if p[x] != tpl.P[x]]
            if changed:
                key = rng.choice(changed); v = tpl.P[key]
        rec = dict(step=k, edit="%s = %s" % (key, v))
        try:
            apply(doc, tpl, key, v)
            p[key] = v
            t0 = time.perf_counter(); doc.recompute(); rec["inc_s"] = round(time.perf_counter() - t0, 3)
            m = measure(doc)
            rec.update(vol=m.get("vol"), area=m.get("area"), red=m["red"], ftypes=m.get("ftypes"))
            rw = readBack(doc, tpl, p)
            rec.update(verdict(m, tpl.truth(p), seen))
            if rw:   # FreeCAD changed a parameter the user set: report it, then follow the document's values
                rec["rewrite"] = rw; rec["v_as_set"] = rec["v"]; rec["v"] = "REWRITE"
                for x, (_a, b) in rw.items():
                    p[x] = b
            if rec["v"] in ("BEYOND", "SILENT", "LOUD"):
                rec["p"] = dict(p)
            if rec["v"] == "SILENT":
                doc.saveAs("%s/%s-silent%d.FCStd" % (OUT, TAG, k))
            if k % 25 == 0:
                rv = reopenVol(doc)
                if (rv is None) != (m.get("vol") is None) or (rv is not None and abs(rv - m["vol"]) > 1e-6 * max(1, abs(rv))):
                    rec["reopen"] = rv; tally["reopen_fail"] += 1
        except Exception as e:
            rec["v"] = "EXC"; rec["exc"] = "%s: %s" % (type(e).__name__, e)
            rec["tb"] = traceback.format_exc().splitlines()[-3:]
        tally[rec["v"]] += 1
        past = rec.get("why") == "past the limit"
        emit(**rec)
    summ = dict(template=T, seed=SEED, steps=STEPS, tally=dict(tally))
    emit(step="summary", **summ)
    open("%s/%s.sum" % (OUT, TAG), "w").write(json.dumps(summ) + "\n")
    print("TRUTH", json.dumps(summ))


if os.environ.get("TRUTH_NOMAIN") != "1":   # TRUTH_NOMAIN=1: load the templates only (probes, reduction)
    try:
        main()
    except Exception:
        emit(step="fatal", tb=traceback.format_exc())
        print(traceback.format_exc())
