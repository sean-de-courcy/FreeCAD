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


def dressOwner():
    """Fillet/Chamfer as studio owners: TRUTH_OWNER_DRESS, default TRUTH_OWNER's value (1)"""
    return os.environ.get("TRUTH_OWNER_DRESS", os.environ.get("TRUTH_OWNER", "1")) == "1"


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

    OWNABLE = ("Pad", "Pocket", "Hole", "Revolution", "Groove")

    def feat(self, kind, name, owner=None, **props):
        # The GUI makes these studio owners (outside every Body, in the studio's list, Command.cpp
        # prepareStudioOwner) once the studio has a solid: TRUTH_OWNER=1 (default) builds them so; 0 keeps them Body
        # members (the in-Body path, ops#844). A pattern's originals stay Body members (owner=False).
        if owner is None:
            owner = os.environ.get("TRUTH_OWNER", "1") == "1"
        if dressOwner() and kind in ("Fillet", "Chamfer") and "Base" in props:
            # In a listed studio the GUI makes a Fillet or Chamfer a studio owner too (Command.cpp makeStudioDressUp):
            # no Base, its picks as StudioPickIds on the part's shown shape (the Body's Tip: dressupGetSelected), a
            # step <name>_at_Part in the Body (the ops#808 path). TRUTH_OWNER_DRESS=0 keeps the Body member
            base, edges = props.pop("Base")
            f = self.doc.addObject("PartDesign::" + kind, name)
            f.StudioPickIds = [PartDesign.studioPickId(base, e) for e in edges]
            for k, x in props.items():
                setattr(f, k, x)
        elif owner and kind in self.OWNABLE and not self.body.Shape.isNull():
            f = self.doc.addObject("PartDesign::" + kind, name)
            f.StudioScope = [self.body.StudioPartId or self.body.Name]
            for k, x in props.items():
                setattr(f, k, x)
        elif kind in self.PATTERNS:
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
        pk = b.feat("Pocket", "RowPocket", owner=False, Profile=s, Length=p["d"])
        b.feat("LinearPattern", "RowPat", Originals=[pk], Direction=(o[0], [""]), Length=p["L"], Occurrences=p["m"])
        s = b.sk("HoleSk", z=p["t"]); circle(s, "H", p["R"], 0, p["rh"])
        hole = b.feat("Pocket", "Hole", owner=False, Profile=s, Type="ThroughAll")
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
        boss = b.feat("Pad", "Boss", owner=False, Profile=s, Length=p["h"])
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


def ivGap(a0, a1, b0, b1):
    """the gap between intervals [a0, a1] and [b0, b1] (negative: they overlap)"""
    return max(b0 - a1, a0 - b1)


def faceAt(shape, z, xmin):
    """the name of the planar +Z face at height z whose centre lies at x > xmin"""
    for i, f in enumerate(shape.Faces, 1):
        c = f.CenterOfMass
        if abs(c.z - z) < 1e-6 and c.x > xmin and abs(f.normalAt(0, 0).z - 1) < 1e-9:
            return "Face%d" % i
    raise RuntimeError("no face at z %s" % z)


class T7:
    """stepped plate: plate a x b x t; Step (x sx..a, full b, hs tall, top S at z t+hs); a boss r at (cx, cy) on the low
    part, Pad UpToFace S (the plane, beyond S's footprint); a rect tool x nx..nx+nw, y ny..ny+nh on a plane at z zn, Pad
    UpToFirst downward (one depth per point: a stepped tool over the step's edge, Onshape O8h); a hole rh at (hx, hy),
    Pocket ThroughAll symmetric. Edits move S (hs, sx), split it (split=1 unsuppresses a groove gw x gd across S, placed
    before the boss; Onshape UT2 keeps the boss at the same height) and delete it (step=0 suppresses Step: the boss must
    fail, Onshape UT3). Onshape UT1-UT4 (notes/onshape-facts.md) agree with this formula at the defaults."""
    P = dict(a=100, b=60, t=8, sx=60, hs=10, cx=30, cy=30, r=8, nx=40, nw=30, ny=40, nh=15, zn=30, hx=85, hy=15, rh=4,
             split=0, gx=75, gw=5, gd=4, step=1)
    R = dict(t=(4, 14), hs=(3, 20), sx=(35, 80), cx=(8, 60), cy=(8, 52), r=(2, 16), nx=(5, 70), nw=(5, 40),
             zn=(15, 45), hx=(10, 95), rh=(1, 10), split=(0, 1), gx=(55, 95), gd=(1, 15), step=(0, 1))
    INT = ("split", "step")
    where = dict(t=("fn", None, None), hs=("fn", None, None), sx=("fn", None, None), split=("fn", None, None),
                 step=("fn", None, None), cx=("datum", "BossSk", "Bx"), cy=("datum", "BossSk", "By"),
                 r=("datum", "BossSk", "Br"), nx=("datum", "NextSk", "Nx"), nw=("datum", "NextSk", "Nw"),
                 zn=("fn", None, None), hx=("datum", "HoleSk", "Hx"), rh=("datum", "HoleSk", "Hr"),
                 gx=("datum", "GrooveSk", "Gx"), gd=("prop", "Groove", "Length"))

    @staticmethod
    def build(b, p):
        a, bb, t, hs = p["a"], p["b"], p["t"], p["hs"]
        s = b.sk("PlateSk"); rect(s, "A", 0, 0, a, bb)
        plate = b.feat("Pad", "Plate", Profile=s, Length=t)
        s = b.sk("StepSk", z=t); rect(s, "S", p["sx"], 0, a - p["sx"], bb)
        step = b.feat("Pad", "Step", Profile=s, Length=hs)
        s = b.sk("GrooveSk", z=t + hs); rect(s, "G", p["gx"], -5, p["gw"], bb + 10)
        groove = b.feat("Pocket", "Groove", Profile=s, Length=p["gd"])
        PartDesign.studioSuppress(groove, True); b.doc.recompute()
        s = b.sk("BossSk", z=t); circle(s, "B", p["cx"], p["cy"], p["r"])
        src = step if step.isDerivedFrom("PartDesign::Feature") and b.body.hasObject(step) else b.body   # an owner: the part's face, as the GUI picks it
        b.feat("Pad", "Boss", Profile=s, Type="UpToFace", UpToFace=(src, [faceAt(src.Shape, t + hs, p["sx"])]))
        s = b.sk("NextSk", z=p["zn"]); rect(s, "N", p["nx"], p["ny"], p["nw"], p["nh"])
        b.feat("Pad", "Next", Profile=s, Type="UpToFirst", Reversed=True)
        s = b.sk("HoleSk"); circle(s, "H", p["hx"], p["hy"], p["rh"])
        b.feat("Pocket", "Hole", Profile=s, Type="ThroughAll", Midplane=True)
        if int(p["split"]):
            PartDesign.studioSuppress(groove, False)
        return plate

    @staticmethod
    def set(doc, key, v, p):
        g = doc.getObject
        if key in ("t", "hs"):
            t = v if key == "t" else p["t"]; hs = v if key == "hs" else p["hs"]
            g("Plate").Length = t; g("Step").Length = hs
            for n in ("StepSk", "BossSk"):
                g(n).AttachmentOffset = App.Placement(V(0, 0, t), App.Rotation())
            g("GrooveSk").AttachmentOffset = App.Placement(V(0, 0, t + hs), App.Rotation())
        elif key == "sx":
            datum(g("StepSk"), "Sx", v); datum(g("StepSk"), "Sw", p["a"] - v)
        elif key == "zn":
            g("NextSk").AttachmentOffset = App.Placement(V(0, 0, v), App.Rotation())
        elif key == "split":
            PartDesign.studioSuppress(g("Groove"), not int(v))
        elif key == "step":
            PartDesign.studioSuppress(g("Step"), not int(v))

    @staticmethod
    def get(doc, key):
        g = doc.getObject
        return dict(t=lambda: g("Plate").Length.Value, hs=lambda: g("Step").Length.Value,
                    sx=lambda: [c.Value for c in g("StepSk").Constraints if c.Name == "Sx"][0],
                    zn=lambda: g("NextSk").AttachmentOffset.Base.z,
                    split=lambda: 0 if g("Groove").Suppressed else 1,
                    step=lambda: 0 if g("Step").Suppressed else 1)[key]()

    @staticmethod
    def truth(p):
        a, b, t, hs, sx = p["a"], p["b"], p["t"], p["hs"], p["sx"]
        if not int(p["step"]):
            return 0.0, 0.0, -1.0, "gone"
        cx, cy, r = p["cx"], p["cy"], p["r"]
        nx, nw, ny, nh, zn = p["nx"], p["nw"], p["ny"], p["nh"], p["zn"]
        hx, hy, rh = p["hx"], p["hy"], p["rh"]
        sp, gx, gw, gd = int(p["split"]), p["gx"], p["gw"], p["gd"]
        top = t + hs
        nr = (nx, ny, nx + nw, ny + nh)
        mar = [sx - cx - r, cx - r, cy - r, b - cy - r, circRectGap(cx, cy, r, *nr),
               nx, a - nx - nw, ny, b - ny - nh, abs(nx - sx), abs(nx + nw - sx), zn - top,
               circInRect(hx, hy, rh, 0, 0, a, b), abs(hx - sx) - rh, circRectGap(hx, hy, rh, *nr),
               math.hypot(hx - cx, hy - cy) - r - rh]
        if sp:
            mar += [gx - sx, a - gx - gw, hs - gd, ivGap(nx, nx + nw, gx, gx + gw),
                    circRectGap(hx, hy, rh, gx, -1e6, gx + gw, 1e6)]
        H = top if hx > sx else t
        Ll = max(0.0, min(nx + nw, sx) - nx); Lh = max(0.0, nx + nw - max(nx, sx))
        hl, hh = zn - t, zn - top
        h0 = hl if nx < sx else hh; h1 = hl if nx + nw < sx else hh
        straddle = Ll > 0 and Lh > 0
        vol = (a * b * t + (a - sx) * b * hs + PI * r * r * hs - PI * rh * rh * H + nh * (Ll * hl + Lh * hh)
               - (gw * b * gd if sp else 0))
        area = (2 * a * b + 2 * (a + b) * t + 2 * b * hs + 2 * (a - sx) * hs + 2 * PI * r * hs
                + 2 * PI * rh * H - 2 * PI * rh * rh
                + 2 * (Ll * hl + Lh * hh) + nh * (h0 + h1) - (nh * hs if straddle else 0)
                + ((2 * b * gd - 2 * gw * gd) if sp else 0))
        regime = "%s-%s-%s" % ("straddle" if straddle else ("low" if Lh == 0 else "high"),
                               "hhigh" if hx > sx else "hlow", "split" if sp else "whole")
        return vol, area, min(mar), regime


class T4:
    """revolved ring: rect ri..ro x 0..h on XZ, Revolution ang deg about Z; Groove 1, a rect ro-gd..ro+5 x gz..gz+gh;
    Groove 2, a circle rc centred on the outer wall at (ro, zc) (a half torus). Truth by Pappus: each groove removes
    2 pi x_c A_sec, the torus surface 2 pi (ro - 2 rc / pi) pi rc; a partial revolve scales the revolved parts by ang/360 and
    adds two end faces of the cut section."""
    P = dict(ri=20, ro=40, h=30, gd=6, gz=4, gh=6, rc=5, zc=20, ang=360)
    R = dict(ri=(2, 45), ro=(15, 60), h=(8, 50), gd=(1, 30), gz=(1, 30), gh=(1, 20), rc=(1, 20), zc=(2, 45),
             ang=(30, 400))
    INT = ("ang",)
    where = dict(ri=("fn", None, None), ro=("fn", None, None), h=("datum", "RingSk", "Ah"),
                 gd=("fn", None, None), gz=("datum", "G1Sk", "Gy"), gh=("datum", "G1Sk", "Gh"),
                 rc=("datum", "G2Sk", "Cr"), zc=("datum", "G2Sk", "Cy"), ang=("prop", "Ring", "Angle"))

    @staticmethod
    def build(b, p):
        o = b.o
        def xz(name):
            s = b.body.newObject("Sketcher::SketchObject", name)
            s.AttachmentSupport = [(o[4], "")]; s.MapMode = "FlatFace"
            PartDesign.studioInsert(s, -1)
            return s
        s = xz("RingSk"); rect(s, "A", p["ri"], 0, p["ro"] - p["ri"], p["h"])
        ring = b.feat("Revolution", "Ring", Profile=s, ReferenceAxis=(o[2], [""]), Angle=p["ang"])
        s = xz("G1Sk"); rect(s, "G", p["ro"] - p["gd"], p["gz"], p["gd"] + 5, p["gh"])
        b.feat("Groove", "G1", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        s = xz("G2Sk"); circle(s, "C", p["ro"], p["zc"], p["rc"])
        b.feat("Groove", "G2", Profile=s, ReferenceAxis=(o[2], [""]), Angle=360)
        return ring

    @staticmethod
    def set(doc, key, v, p):
        g = doc.getObject
        ro = v if key == "ro" else p["ro"]; gd = v if key == "gd" else p["gd"]
        if key == "ri":   # the inner wall moves, the outer stays
            datum(g("RingSk"), "Aw", ro - v); datum(g("RingSk"), "Ax", v); return
        if key == "ro":   # the outer wall carries both grooves (one variable driving them)
            datum(g("RingSk"), "Aw", ro - p["ri"]); datum(g("G2Sk"), "Cx", ro)
        datum(g("G1Sk"), "Gw", gd + 5); datum(g("G1Sk"), "Gx", ro - gd)

    @staticmethod
    def get(doc, key):
        g = doc.getObject
        d = lambda sk, n: [c.Value for c in g(sk).Constraints if c.Name == n][0]
        if key == "ri":
            return d("RingSk", "Ax")
        if key == "ro":
            return d("RingSk", "Ax") + d("RingSk", "Aw")
        return d("G1Sk", "Gw") - 5

    @staticmethod
    def truth(p):
        ri, ro, h, gd, gz, gh, rc, zc, ang = (p[k] for k in ("ri", "ro", "h", "gd", "gz", "gh", "rc", "zc", "ang"))
        w = ro - ri
        mar = [ri, w, w - gd, gz, h - gz - gh, w - rc, zc - rc, h - zc - rc, ivGap(gz, gz + gh, zc - rc, zc + rc)]
        if ang > 360:
            mar.append(360 - ang)
        f = min(ang, 360) / 360.0
        sec = w * h - gd * gh - PI * rc * rc / 2
        xs = (ro * ro - ri * ri) / 2.0 * h               # first moment of the ring section about Z
        x1 = (ro - gd / 2.0) * gd * gh
        x2 = (ro - 4 * rc / (3 * PI)) * PI * rc * rc / 2
        vol = f * 2 * PI * (xs - x1 - x2)
        # revolved boundary: bottom and top annuli, inner wall, outer wall minus both bands, groove 1's floor and walls,
        # the half torus
        prof = (2 * PI * (ro * ro - ri * ri) + 2 * PI * ri * h + 2 * PI * ro * (h - gh - 2 * rc)
                + 2 * PI * (ro - gd) * gh + 2 * PI * (ro * ro - (ro - gd) ** 2)
                + 2 * PI * (ro - 2 * rc / PI) * PI * rc)
        area = f * prof + (2 * sec if ang < 360 else 0)
        return vol, area, min(mar), "full" if ang >= 360 else "part"


def varDriven(base, derived, doc_):
    """T6: base (T1 or T2) with every walked parameter a Variable Studio variable, bound as '#name' (Onshape's form).
    derived: key -> (FreeCAD expression, the same in Python): a parameter no longer walked, computed by a ternary."""
    R_ = {k: x for k, x in base.R.items() if k not in derived}
    INT_ = tuple(k for k in getattr(base, "INT", ()) if k in R_)

    class T6x(base):
        __doc__ = doc_
        P = dict(base.P)
        R = R_
        where = {k: ("fn", None, None) for k in R_}
        INT = INT_

        @staticmethod
        def full(p):
            q = dict(p)
            for k, (_e, f) in derived.items():
                q[k] = f(q)
            return q

        @classmethod
        def build(cls, b, p):
            doc = b.doc
            first = base.build(b, cls.full(p))
            vs = doc.addObject("App::VarSet", "VarSet"); vs.Label = "Variable Studio 1"
            App.DocumentTabs.setVariableStudio(vs)
            for k in cls.R:
                kind = "App::PropertyInteger" if k in cls.INT else "App::PropertyLength"
                vs.addProperty(kind, k); setattr(vs, k, p[k])
            for k in list(cls.R) + list(derived):
                how, obj, prop = base.where[k]
                e = derived[k][0] if k in derived else "#" + k
                o = doc.getObject(obj)
                if how == "datum":
                    o.setExpression("Constraints." + prop, e)
                    if getattr(base, "CENTRED", False) and k in ("a", "b"):
                        o.setExpression("Constraints." + ("Ax" if k == "a" else "Ay"), "-(%s) / 2" % e)
                else:
                    o.setExpression(prop, e)
                if k == "t":   # the sketches on the plate's top follow it
                    for s in doc.Objects:
                        if s.isDerivedFrom("Sketcher::SketchObject") and abs(s.AttachmentOffset.Base.z - p["t"]) < 1e-9:
                            s.setExpression(".AttachmentOffset.Base.z", "#t")
            doc.recompute()
            return first

        @classmethod
        def truth(cls, p):
            return base.truth(cls.full(p))

        @staticmethod
        def set(doc, key, v, p):
            setattr(doc.getObject("VarSet"), key, v)

        @staticmethod
        def get(doc, key):
            x = getattr(doc.getObject("VarSet"), key)
            return float(getattr(x, "Value", x))

    return T6x


T6a = varDriven(T1, dict(D=("#d < 6 mm ? #d + 4 mm : #d * 1.5", lambda q: q["d"] + 4 if q["d"] < 6 else q["d"] * 1.5)),
                "T6a: T1 through Variable Studio variables; the countersink diameter D = d < 6 ? d + 4 : 1.5 d (a ternary)")
T6b = varDriven(T2, dict(m=("#L > 60 mm ? 5 : (#L > 35 mm ? 3 : 2)", lambda q: 5 if q["L"] > 60 else (3 if q["L"] > 35 else 2))),
                "T6b: T2 through Variable Studio variables; the row count m = L > 60 ? 5 : (L > 35 ? 3 : 2) (nested ternaries)")
T6a.P["D"] = T6a.full(T6a.P)["D"]; T6b.P["m"] = T6b.full(T6b.P)["m"]


class T8:
    """plate a x b x t; Hole features from points on the top: a through counterbore (d1, D1, depth k1) at (20, 20), a
    through counterdrill (d2, D2, depth k2, 90 deg) at (50, 20), a blind hole d3 deep L3 with a 118 deg point (tip=1: L3
    to the tip, DrillForDepth; tip=0: to the shoulder) at (80, 20), a through hole d5 at (50, 45); a chamfer of the 4
    vertical edges, ch=0 two distances s1, s2, ch=1 distance s1 and angle ang (s2 = s1 tan ang). The triangle s1 x s2 is
    symmetric in which face takes which, so V and A don't depend on the edge's orientation."""
    P = dict(a=100, b=60, t=12, d1=6, D1=11, k1=4, d2=6, D2=12, k2=2, d3=5, L3=8, tip=1, d5=4, s1=3, s2=5, ang=30, ch=0)
    R = dict(t=(6, 18), d1=(2, 12), D1=(4, 24), k1=(0.5, 16), d2=(2, 12), D2=(4, 24), k2=(0.5, 12), d3=(2, 12),
             L3=(2, 20), tip=(0, 1), d5=(1, 14), s1=(0.5, 16), s2=(0.5, 16), ang=(10, 80), ch=(0, 1))
    INT = ("tip", "ch")
    C = dict(H1=(20, 20), H2=(50, 20), H3=(80, 20), H5=(50, 45))
    where = dict(t=("prop", "Plate", "Length"), d1=("prop", "H1", "Diameter"), D1=("prop", "H1", "HoleCutDiameter"),
                 k1=("prop", "H1", "HoleCutDepth"), d2=("prop", "H2", "Diameter"), D2=("prop", "H2", "HoleCutDiameter"),
                 k2=("prop", "H2", "HoleCutDepth"), d3=("prop", "H3", "Diameter"), L3=("prop", "H3", "Depth"),
                 tip=("fn", None, None), d5=("prop", "H5", "Diameter"), s1=("prop", "Cham", "Size"),
                 s2=("prop", "Cham", "Size2"), ang=("prop", "Cham", "Angle"), ch=("fn", None, None))

    @classmethod
    def build(cls, b, p):
        s = b.sk("PlateSk"); rect(s, "A", 0, 0, p["a"], p["b"])
        plate = b.feat("Pad", "Plate", Profile=s, Length=p["t"])
        b.feat("Chamfer", "Cham", Base=(plate, edgeSet(plate, 0)), ChamferType="Two distances", Size=p["s1"],
               Size2=p["s2"], Angle=p["ang"])
        if int(p["ch"]):
            b.doc.getObject("Cham").ChamferType = "Distance and Angle"
        common = dict(Threaded=False, HoleCutCustomValues=True)
        for n in ("H1", "H2", "H3", "H5"):
            s = b.sk(n + "Sk", z=p["t"]); point(s, n, *cls.C[n])
        b.feat("Hole", "H1", Profile=b.doc.getObject("H1Sk"), Diameter=p["d1"], DepthType="ThroughAll",
               HoleCutType="Counterbore", **common)
        g = b.doc.getObject("H1"); g.HoleCutDiameter = p["D1"]; g.HoleCutDepth = p["k1"]
        b.feat("Hole", "H2", Profile=b.doc.getObject("H2Sk"), Diameter=p["d2"], DepthType="ThroughAll",
               HoleCutType="Counterdrill", HoleCutCountersinkAngle=90, **common)
        g = b.doc.getObject("H2"); g.HoleCutDiameter = p["D2"]; g.HoleCutDepth = p["k2"]
        b.feat("Hole", "H3", Profile=b.doc.getObject("H3Sk"), Diameter=p["d3"], DepthType="Dimension", Depth=p["L3"],
               DrillPoint="Angled", DrillPointAngle=118, DrillForDepth=bool(int(p["tip"])), **common)
        b.feat("Hole", "H5", Profile=b.doc.getObject("H5Sk"), Diameter=p["d5"], DepthType="ThroughAll", **common)
        b.doc.recompute()
        return plate

    @staticmethod
    def set(doc, key, v, p):
        if key == "tip":
            doc.getObject("H3").DrillForDepth = bool(int(v))
        else:
            doc.getObject("Cham").ChamferType = "Distance and Angle" if int(v) else "Two distances"

    @staticmethod
    def get(doc, key):
        if key == "tip":
            return 1 if doc.getObject("H3").DrillForDepth else 0
        return 1 if doc.getObject("Cham").ChamferType == "Distance and Angle" else 0

    @classmethod
    def truth(cls, p):
        a, b, t = p["a"], p["b"], p["t"]
        s1 = p["s1"]; s2 = s1 * math.tan(math.radians(p["ang"])) if int(p["ch"]) else p["s2"]
        r1, R1, k1 = p["d1"] / 2, p["D1"] / 2, p["k1"]
        r2, R2, k2 = p["d2"] / 2, p["D2"] / 2, p["k2"]
        r3, L3, r5 = p["d3"] / 2, p["L3"], p["d5"] / 2
        hc = r3 * math.tan(math.radians(31))           # the 118 deg point's height
        cone2 = R2 - r2                                # the 90 deg counterdrill's cone height
        Lc = L3 - hc if int(p["tip"]) else L3          # the cylinder's length
        cuts = dict(H1=R1, H2=R2, H3=r3, H5=r5)
        sm = max(s1, s2)
        mar = [R1 - r1, t - k1, R2 - r2, t - k2 - cone2, Lc, t - Lc - hc, min(a, b) / 2 - sm]
        ks = list(cls.C)
        for i, n in enumerate(ks):
            cx, cy = cls.C[n]
            mar.append(circInRect(cx, cy, cuts[n], 0, 0, a, b) - sm)
            for m in ks[i + 1:]:
                mar.append(math.hypot(cx - cls.C[m][0], cy - cls.C[m][1]) - cuts[n] - cuts[m])
        vol = (a * b * t - 2 * s1 * s2 * t
               - (PI * R1 * R1 * k1 + PI * r1 * r1 * (t - k1))
               - (PI * R2 * R2 * k2 + PI * cone2 / 3 * (R2 * R2 + R2 * r2 + r2 * r2) + PI * r2 * r2 * (t - k2 - cone2))
               - (PI * r3 * r3 * Lc + PI * r3 * r3 * hc / 3)
               - PI * r5 * r5 * t)
        area = (2 * a * b + 2 * (a + b) * t - 4 * t * (s1 + s2) - 4 * s1 * s2 + 4 * t * math.hypot(s1, s2)
                + (-PI * R1 * R1 + 2 * PI * R1 * k1 + PI * (R1 * R1 - r1 * r1) + 2 * PI * r1 * (t - k1) - PI * r1 * r1)
                + (-PI * R2 * R2 + 2 * PI * R2 * k2 + PI * (R2 + r2) * cone2 * math.sqrt(2)
                   + 2 * PI * r2 * (t - k2 - cone2) - PI * r2 * r2)
                + (-PI * r3 * r3 + 2 * PI * r3 * Lc + PI * r3 * math.hypot(r3, hc))
                + (2 * PI * r5 * t - 2 * PI * r5 * r5))
        return vol, area, min(mar), "%s-%s" % ("angle" if int(p["ch"]) else "two", "tip" if int(p["tip"]) else "shoulder")


TEMPLATES = dict(T1=T1, T2=T2, T3=T3, T4=T4, T5f=T5f, T5c=T5c, T6a=T6a, T6b=T6b, T7=T7, T8=T8)


# ------------------------------------------------------------------ live edits
def datum(sk, name, v):
    for i, c in enumerate(sk.Constraints):
        if c.Name == name:
            sk.setDatum(i, App.Units.Quantity("%s mm" % v))
            return
    raise KeyError(name)


def apply(doc, tpl, key, v, p=None):
    how, obj, prop = tpl.where[key]
    o = doc.getObject(obj) if obj else None
    if how == "fn":   # the template sets it (several properties as one user edit)
        tpl.set(doc, key, v, p)
    elif how == "datum":
        if getattr(tpl, "CENTRED", False) and key in ("a", "b"):   # a centred plate stays centred (one edit, both datums)
            datum(o, prop, v)
            datum(o, "Ax" if key == "a" else "Ay", -v / 2.0)
        else:
            datum(o, prop, v)
    elif how == "edges":
        box = doc.getObject("Box")
        if not doc.getObject("Part").hasObject(o):   # a studio owner (outside the Body): its picks are ids
            o.StudioPickIds = [PartDesign.studioPickId(box, e) for e in edgeSet(box, v)]
        else:
            o.Base = (box, edgeSet(box, v))
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
        o = doc.getObject(obj) if obj else None
        if how == "fn":
            x = float(tpl.get(doc, key))
        elif how == "datum":
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
    if regime == "gone":   # Onshape UT3: the up-to-face boss fails (EXTRUDE_SELECT_TERMINATING_SURFACE); so must FreeCAD's
        rec["why"] = "target gone"
        rec["v"] = "OK" if "Boss" in m.get("red", []) else "SILENT"
    elif mar < -EPS:
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
            apply(doc, tpl, key, v, p)
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
        past = rec.get("why") in ("past the limit", "target gone")
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
