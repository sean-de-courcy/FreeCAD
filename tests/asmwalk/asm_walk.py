# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH assembly robustness walk (design B, notes/robustness-sweep.md section 2; ops#640).
#
# A seeded random walk over a designed assembly: studio Blk (a PartDesign box, optional top fillet)
# grounded, a Pin (cylinder or hexagonal prism) fastened top face onto Blk's top face, and a linear
# pattern of the Pin along Blk's X edge. After every step:
#   1. the solve converges (0) or something says why (a joint invalid, the pattern's State),
#   2. placements match the closed form: Pin's top-face centre = Blk's top-face centre + offset along
#      +Z, Pin unrotated, copy i = seed translated by i * distance along X, Blk unmoved,
#   3. an undo step restores the snapshot taken before the undone edit exactly,
#   4. a fresh document built from the same parameter vector gives the same placements.
# Verdicts: OK, LOUD (an error raised or a joint invalid where the closed form is defined),
# SILENT (no error, wrong placement / undo / rebuild): the target.
#
# Run: FreeCADCmd.exe asm_walk.py, env ASMWALK_SEED, ASMWALK_STEPS, ASMWALK_OUT (jsonl path).
# Designed geometry only.

import json
import os
import random
import sys
import time
import traceback

import FreeCAD as App

import AssemblyPattern
import JointObject

V = App.Vector
TOL = 1e-6

SEED = int(os.environ.get("ASMWALK_SEED", "1"))
STEPS = int(os.environ.get("ASMWALK_STEPS", "60"))
OUT = os.environ.get("ASMWALK_OUT", "")
EDITS = os.environ.get("ASMWALK_EDITS", "")
OFFSET_MODE = os.environ.get("ASMWALK_OFFSET", "observed")  # "onshape": expect +offset along the first pick  # comma list to restrict the edit kinds


UNDO_CAP = 20


def defaults():
    return dict(pocket=0.0, L=20.0, W=20.0, H=10.0, fillet=0.0, pin="cyl", R=5.0, PH=20.0,
                count=10, dist=25.0, offset=0.0)


class Model:
    """The assembly, built from a parameter vector; edits keep self.p in step."""

    def __init__(self, p, name):
        self.p = dict(p)
        self.doc = App.newDocument(name)
        self.doc.UndoMode = 1

        d = self.doc
        self.blkBody = d.addObject("PartDesign::Body", "Blk")
        self.box = self.blkBody.newObject("PartDesign::AdditiveBox", "BlkBox")
        self.box.Length, self.box.Width, self.box.Height = p["L"], p["W"], p["H"]
        self.fil = None
        self.pinBody = d.addObject("PartDesign::Body", "Pin")
        self.pinFeat = None
        self.makePin(p["pin"])
        d.recompute()
        if p["fillet"] > 0:
            self.addFillet(p["fillet"])
        if p.get("pocket", 0) > 0:
            self.addPocket(p["pocket"])
        d.recompute()
        self.asm = d.addObject("Assembly::AssemblyObject", "Assembly")
        self.asm.Type = "Assembly"
        self.joints = self.asm.newObject("Assembly::JointGroup", "Joints")
        self.blk = self.link("BlkI", self.blkBody, V(0, 0, 0))
        self.seed = self.link("PinI", self.pinBody, V(60, 0, 0))
        d.recompute()
        g = self.joints.newObject("App::FeaturePython", "GroundBlk")
        JointObject.GroundedJoint(g, self.blk)
        self.joint = None
        self.lastSeed = None
        self.makeMate()
        d.recompute()
        self.pattern = AssemblyPattern.makePattern(self.asm, "Linear", [self.seed],
                                                   (self.blk, [self.xEdge()]))
        self.pattern.Count = p["count"]
        self.pattern.Distance = p["dist"]
        d.recompute()

    # --- building blocks ---
    def link(self, name, src, at):
        l = self.asm.newObject("App::Link", name)
        l.LinkedObject = src
        l.Placement = App.Placement(at, App.Rotation())
        return l

    def makePin(self, kind):
        """Pin: a sketch on XY (circle or hexagon of circumradius R about the origin) padded PH."""
        import Part, Sketcher, math
        if self.pinFeat is None:
            self.pinSketch = self.pinBody.newObject("Sketcher::SketchObject", "PinSketch")
            self.pinSketch.AttachmentSupport = [(self.pinBody.Origin.OriginFeatures[3], "")]  # XY plane
            self.pinSketch.MapMode = "FlatFace"
            self.pinFeat = self.pinBody.newObject("PartDesign::Pad", "PinPad")
            self.pinFeat.Profile = self.pinSketch
        self.pinFeat.Length = self.p["PH"]
        self.drawProfile(kind)

    def resizeProfile(self):
        """A size edit in place: the same geometry (tags kept), new radius / vertices."""
        import math
        sk = self.pinSketch
        R = self.p["R"]
        geo = sk.Geometry
        if self.p["pin"] == "cyl":
            geo[0].Radius = R
        else:
            pts = [V(R * math.cos(math.pi / 3 * k), R * math.sin(math.pi / 3 * k), 0) for k in range(6)]
            for k in range(6):
                geo[k].StartPoint, geo[k].EndPoint = pts[k], pts[(k + 1) % 6]
        sk.Geometry = geo

    def drawProfile(self, kind):
        import Part, math
        sk = self.pinSketch
        sk.deleteAllGeometry()
        R = self.p["R"]
        if kind == "cyl":
            sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), R))
        else:
            pts = [V(R * math.cos(math.pi / 3 * k), R * math.sin(math.pi / 3 * k), 0) for k in range(6)]
            for k in range(6):
                sk.addGeometry(Part.LineSegment(pts[k], pts[(k + 1) % 6]))

    def addFillet(self, r):
        """A fillet on the top's 4 edges, picked on the body's tip as the GUI does (its Base is the
        tip feature, a suppressed one included)."""
        base = self.blkBody.Tip
        shape = base.Shape
        H = self.box.Height.Value
        edges = [f"Edge{i}" for i, e in enumerate(shape.Edges, 1)
                 if all(abs(v.Point.z - H) < 1e-7 for v in e.Vertexes)
                 and abs(abs(e.Vertexes[0].Point.x - e.Vertexes[-1].Point.x) + abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y)
                         - max(abs(e.Vertexes[0].Point.x - e.Vertexes[-1].Point.x), abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y))) < 1e-9]
        self.fil = self.blkBody.newObject("PartDesign::Fillet", "BlkFillet")
        self.fil.Base = (base, edges)
        self.fil.Radius = r

    def addPocket(self, a):
        """A full-width pocket 3 deep over x in [L - a, L] of the top, following the box by expressions."""
        pk = self.blkBody.newObject("PartDesign::SubtractiveBox", "BlkPocket")
        pk.Length, pk.Height = a, 3
        pk.setExpression("Width", "BlkBox.Width + 2 mm")
        pk.setExpression(".Placement.Base.x", "BlkBox.Length - Length")
        pk.Placement = App.Placement(V(0, -1, 0), App.Rotation())
        pk.setExpression(".Placement.Base.z", "BlkBox.Height - 3 mm")
        return pk

    @staticmethod
    def topFace(shape):
        zmax = shape.BoundBox.ZMax
        found = [f"Face{i}" for i, f in enumerate(shape.Faces, 1)
                 if f.Surface.TypeId == "Part::GeomPlane"
                 and abs(f.CenterOfMass.z - zmax) < 1e-6 and f.normalAt(0, 0).z > 0.5]
        assert len(found) == 1, found
        return found[0]

    def makeMate(self):
        tb = self.topFace(self.blkBody.Shape)
        tp = self.topFace(self.pinBody.Shape)
        j = self.joints.newObject("App::FeaturePython", "Fastened")
        JointObject.Joint(j, 0)
        j.Proxy.setJointConnectors(j, [[self.seed, [tp, tp]], [self.blk, [tb, tb]]])
        j.Offset2 = App.Placement(V(0, 0, self.p["offset"]), App.Rotation())
        self.joint = j

    def xEdge(self):
        for i, e in enumerate(self.blkBody.Shape.Edges, 1):
            p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if min(p0.Length, p1.Length) < 1e-9 and abs(abs((p1 - p0).normalize().x) - 1) < 1e-12:
                self.p["dir"] = 1.0 if (p1 - p0).x > 0 else -1.0
                return f"Edge{i}"
        raise RuntimeError("no X edge")

    def jointValid(self):
        try:
            return bool(self.joint.isValid())
        except Exception:
            return False

    def refSwapped(self):
        return self.joint.Reference1[0] == self.blk

    def close(self):
        App.closeDocument(self.doc.Name)

    # --- observation ---
    def copies(self):
        return sorted((c for c in (self.pattern.Instances or []) if c), key=lambda c: c.PatternIndex)

    def snapshot(self):
        s = {}
        for o in self.asm.Group:
            if o.TypeId == "App::Link":
                # copies by pattern index: a regenerated copy may get a new name
                idx = getattr(o, "PatternIndex", None) if AssemblyPattern.isPatternCopy(o) else None
                key = f"copy{idx}" if idx is not None else o.Name
                s[key] = [round(x, 9) for x in list(o.Placement.Base) + list(o.Placement.Rotation.Q)]
        s["_blkV"] = round(self.blkBody.Shape.Volume, 6) if not self.blkBody.Shape.isNull() else None
        s["_pinV"] = round(self.pinBody.Shape.Volume, 6) if not self.pinBody.Shape.isNull() else None
        return s

    def keyed(self):
        """Placements keyed by role, comparable across documents."""
        k = {"blk": self.blk.Placement, "seed": self.seed.Placement}
        for c in self.copies():
            k[f"copy{c.PatternIndex}"] = c.Placement
        return k


def beyond(p):
    r = p["fillet"]
    return r > 0 and r >= min(p["H"], p["L"] / 2, p["W"] / 2) - 1e-6


def errors(m):
    """The loud signals: invalid objects and their messages."""
    out = []
    for o in m.doc.Objects:
        try:
            if "Invalid" in o.State or "Error" in o.State:
                out.append(f"{o.Name}:{o.State}")
        except Exception:
            pass
    try:
        if not m.joint.isValid():
            out.append("joint invalid: " + m.joint.getStatusString())
    except Exception as e:
        out.append(f"joint gone: {e}")
    return out


def check(m):
    """Closed-form placements. Returns a list of mismatches."""
    p = m.p
    bad = []
    if not m.blk.Placement.isSame(App.Placement(), 1e-9):
        bad.append(f"Blk moved: {m.blk.Placement}")
    bs, ps = m.blkBody.Shape, m.pinBody.Shape
    if bs.isNull() or ps.isNull():
        return ["null shape"]
    if p.get("pocket", 0) > 0:
        # AR2: a pocket over x in [L - pocket, L] of the top, 3 deep: the remaining top face's centroid
        exp_top = V((p["L"] - p["pocket"]) / 2, p["W"] / 2, p["H"])
    else:
        exp_top = V(p["L"] / 2, p["W"] / 2, p["H"])
    btf = bs.getElement(Model.topFace(bs))
    if (btf.CenterOfMass - exp_top).Length > 1e-5:
        bad.append(f"Blk top centre {btf.CenterOfMass} != {exp_top}")
    ptf = ps.getElement(Model.topFace(ps)).CenterOfMass  # pin's own frame
    if abs(ptf.z - p["PH"]) > 1e-6:
        bad.append(f"Pin top z {ptf.z} != {p['PH']}")
    sp = m.seed.Placement
    if m.jointValid():
        # the grounded-at-pick swap reverses the offset (asm-walk finding 1): sign by Reference1
        sign = -1.0 if m.refSwapped() else 1.0
        want = exp_top + V(0, 0, sign * p["offset"]) if OFFSET_MODE == "observed" else exp_top + V(0, 0, p["offset"])
        got = sp.multVec(ptf)
        if (got - want).Length > TOL:
            bad.append(f"seed top centre {got} != {want}")
        if not sp.Rotation.isSame(App.Rotation(), 1e-9):
            bad.append(f"seed rotated {sp.Rotation}")
    elif m.lastSeed is not None and not sp.isSame(m.lastSeed, TOL):
        # an invalid mate drives nothing: the instance stays where it was (B3)
        bad.append(f"seed moved under an invalid mate: {m.lastSeed.Base} -> {sp.Base}")
    cs = m.copies()
    if len(cs) != p["count"] - 1:
        bad.append(f"{len(cs)} copies, count {p['count']}")
    for c in cs:
        e = App.Placement(V(p.get("dir", 1.0) * p["dist"] * c.PatternIndex, 0, 0), App.Rotation()).multiply(sp)
        if not c.Placement.isSame(e, TOL):
            bad.append(f"copy {c.PatternIndex} at {c.Placement.Base} != {e.Base}")
    return bad


# --- edits: each returns a description; the parameter vector is updated to the intended state ---

def e_blkdims(m, r):
    k = r.choice(["L", "W", "H"])
    v = round(r.uniform(*{"L": (8, 40), "W": (8, 40), "H": (4, 20)}[k]), 3)
    if m.p["fillet"] and v <= 2 * m.p["fillet"] + 0.5:
        v = 2 * m.p["fillet"] + 1.0
    pk = m.doc.getObject("BlkPocket")
    if k == "L" and pk is not None and v <= pk.Length.Value + 1:
        v = round(pk.Length.Value + 2, 3)
    m.p[k] = v
    setattr(m.box, {"L": "Length", "W": "Width", "H": "Height"}[k], v)
    return f"Blk {k}={v}"


def e_fillet(m, r):
    if m.p.get("pocket", 0) > 0:
        return "noop"
    if m.fil is None:
        rad = round(r.uniform(0.5, min(m.p["L"], m.p["W"], m.p["H"]) / 2 - 0.5), 3)
        if rad <= 0.2:
            return "noop"
        m.addFillet(rad)
        m.p["fillet"] = rad
        return f"fillet add r={rad}"
    if m.fil.Suppressed:
        m.fil.Suppressed = False
        m.p["fillet"] = m.fil.Radius.Value
        return "fillet unsuppress"
    if r.random() < 0.5:
        m.fil.Suppressed = True
        m.p["fillet"] = 0.0
        return "fillet suppress"
    rad = round(r.uniform(0.5, min(m.p["L"], m.p["W"], m.p["H"]) / 2 - 0.5), 3)
    m.fil.Radius = rad
    m.p["fillet"] = rad
    return f"fillet r={rad}"


def e_pindims(m, r):
    k = r.choice(["R", "PH"])
    v = round(r.uniform(*{"R": (1, 8), "PH": (5, 30)}[k]), 3)
    m.p[k] = v
    if k == "R":
        m.resizeProfile()
    else:
        m.pinFeat.Length = v
    return f"Pin {k}={v}"


def e_count(m, r):
    v = r.choice([1, 2, 3, 5, 6, 10, 12, r.randint(1, 20)])
    m.p["count"] = v
    m.pattern.Count = v
    return f"count={v}"


def e_dist(m, r):
    v = round(r.uniform(5, 40), 3)
    m.p["dist"] = v
    m.pattern.Distance = v
    return f"dist={v}"


def e_offset(m, r):
    v = round(r.choice([0.0, r.uniform(-5, 5)]), 3)
    m.p["offset"] = v
    m.joint.Offset2 = App.Placement(V(0, 0, v), App.Rotation())
    return f"offset={v}"


def e_delcopy(m, r):
    cs = m.copies()
    if not cs:
        return "noop"
    c = r.choice(cs)
    i = c.PatternIndex
    m.doc.removeObject(c.Name)
    return f"delete copy {i}"


def e_profile(m, r):
    """R1.8: the Pin's sketch profile swapped (circle <-> hexagon) in the same sketch."""
    kind = "hex" if m.p["pin"] == "cyl" else "cyl"
    m.p["pin"] = kind
    m.drawProfile(kind)
    return f"profile -> {kind}"


def e_reopen(m, r):
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"asmwalk_{SEED}_{os.getpid()}.FCStd")
    m.doc.saveAs(path)
    name = m.doc.Name
    App.closeDocument(name)
    d = App.openDocument(path)
    d.UndoMode = 1
    m.doc = d
    m.blkBody, m.box, m.pinBody = d.getObject("Blk"), d.getObject("BlkBox"), d.getObject("Pin")
    m.fil = d.getObject("BlkFillet")
    m.pinFeat, m.pinSketch = d.getObject("PinPad"), d.getObject("PinSketch")
    m.asm, m.joints = d.getObject("Assembly"), d.getObject("Joints")
    m.blk, m.seed, m.joint = d.getObject("BlkI"), d.getObject("PinI"), d.getObject("Fastened")
    m.pattern = [o for o in d.Objects if hasattr(o, "Instances") and hasattr(o, "Distance")][0]
    d.recompute()
    return "save + reopen"


def e_pocket(m, r):
    """AR2: a full-width pocket 3 deep over the top's x in [L - a, L]; toggled by suppress."""
    pk = m.doc.getObject("BlkPocket")
    if pk is None:
        if m.fil is not None and not m.fil.Suppressed:
            return "noop"  # keep the closed form simple: no fillet with the pocket
        a = round(r.uniform(0.2, 0.7) * m.p["L"], 3)
        m.addPocket(a)
        m.p["pocket"] = a
        return f"pocket a={a}"
    if pk.Suppressed:
        if m.fil is not None and not m.fil.Suppressed:
            return "noop"
        pk.Suppressed = False
        m.p["pocket"] = pk.Length.Value
        return "pocket unsuppress"
    pk.Suppressed = True
    m.p["pocket"] = 0.0
    return "pocket suppress"


KINDS = [(e_blkdims, 20), (e_fillet, 10), (e_pindims, 12), (e_count, 12), (e_dist, 8),
         (e_offset, 8), (e_delcopy, 8), (e_reopen, 3), (e_pocket, 6), (e_profile, int(os.environ.get('ASMWALK_PROFILE_W', '2')))]
# plus 'undo' (10) and 'delseed+undo' (6) handled in the walk


def rebuild_matches(m, i):
    """A fresh document from the same parameter vector: same placements?"""
    f = None
    try:
        f = Model(m.p, f"Fresh{i}")
        f.doc.recompute()
        a, b = m.keyed(), f.keyed()
        diff = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                diff.append(f"{k} only in {'walk' if k in a else 'fresh'}")
            elif not a[k].isSame(b[k], TOL):
                diff.append(f"{k}: walk {a[k].Base} fresh {b[k].Base}")
        return diff
    finally:
        if f:
            f.close()


def main():
    r = random.Random(SEED)
    log = open(OUT, "w") if OUT else sys.stdout
    m = Model(defaults(), f"Walk{SEED}")
    hist = []  # (snapshot before, params before) per committed transaction
    names = [k for k, _ in KINDS] + ["undo", "delseed"]
    weights = [w for _, w in KINDS] + [10, 6]
    if EDITS:
        keep = set(EDITS.split(","))
        sel = [(n, w) for n, w in zip(names, weights) if (n if isinstance(n, str) else n.__name__[2:]) in keep]
        names, weights = [s[0] for s in sel], [s[1] for s in sel]
    counts = {}
    m.asm.solve(); m.doc.recompute()
    log.write(json.dumps({"seed": SEED, "step": -1, "kind": "init", "verdict": "OK" if not check(m) else "SILENT", "bad": check(m), "p": m.p}, default=str) + chr(10))
    for step in range(STEPS):
        kind = r.choices(names, weights)[0]
        kname = kind if isinstance(kind, str) else kind.__name__[2:]
        rec = {"seed": SEED, "step": step, "kind": kname}
        t0 = time.time()
        try:
            before, pbefore = m.snapshot(), dict(m.p)
            if kname == "undo":
                if not hist:
                    continue
                snap, pp = hist.pop()
                m.doc.undo()
                m.doc.recompute()
                m.p = pp
                # re-find features the undo brought back
                m.pinFeat, m.pinSketch = m.doc.getObject("PinPad"), m.doc.getObject("PinSketch")
                m.fil = m.doc.getObject("BlkFillet")
                now = m.snapshot()
                diff = [k for k in set(snap) | set(now) if snap.get(k) != now.get(k)]
                rec["desc"] = "undo"
                rec["undo_diff"] = {k: [snap.get(k), now.get(k)] for k in diff}
            elif kname == "reopen":
                rec["desc"] = e_reopen(m, r)
                hist.clear()
                now = m.snapshot()
                diff = [k for k in set(before) | set(now) if before.get(k) != now.get(k)]
                rec["undo_diff"] = {k: [before.get(k), now.get(k)] for k in diff}  # reopen = same state
            elif kname == "delseed":
                m.doc.openTransaction("delseed")
                name = m.seed.Name
                m.doc.removeObject(name)
                m.doc.recompute()
                m.doc.commitTransaction()
                m.doc.undo()
                m.doc.recompute()
                m.seed = m.doc.getObject(name)
                m.joint = m.doc.getObject("Fastened")
                now = m.snapshot()
                diff = [k for k in set(before) | set(now) if before.get(k) != now.get(k)]
                rec["desc"] = "delete seed + undo"
                rec["undo_diff"] = {k: [before.get(k), now.get(k)] for k in diff}
            else:
                n0 = m.doc.UndoCount
                names0 = list(m.doc.UndoNames)
                m.doc.openTransaction(kname)
                rec["desc"] = kind(m, r)
                m.doc.recompute()
                m.doc.commitTransaction()
                n1 = m.doc.UndoCount
                # an edit that changed nothing leaves no transaction; headless the stack holds 20
                # (DocumentP's default; no Python setter), so a full stack stays at 20
                names1 = list(m.doc.UndoNames)
                if n1 > n0 or (n1 == n0 == UNDO_CAP and names1 != names0):
                    hist.append((before, pbefore))
                    del hist[:-UNDO_CAP]
            if m.seed is None or m.joint is None:
                rec["verdict"] = "SILENT"
                rec["bad"] = ["seed or joint not restored"]
            else:
                rc = m.asm.solve()
                m.doc.recompute()
                rec["solve"] = rc
                errs = errors(m)
                bad = check(m)
                rec["errors"], rec["bad"] = errs, bad
                if rec.get("undo_diff"):
                    bad = bad + ["undo: " + ",".join(sorted(rec["undo_diff"]))]
                    rec["bad"] = bad
                if beyond(m.p):
                    rec["fresh"] = []
                    rec["verdict"] = "BEYOND" if (errs or rc != 0) else ("SILENT?" if bad else "BEYOND-OK")
                    raise StopIteration
                fresh = rebuild_matches(m, step) if m.jointValid() else []
                rec["fresh"] = fresh
                if not bad and not fresh:
                    rec["verdict"] = "LOUD" if (errs or rc != 0) else "OK"
                elif errs or rc != 0:
                    rec["verdict"] = "LOUD" if not rec.get("undo_diff") and not fresh else "SILENT?"
                else:
                    rec["verdict"] = "SILENT"
        except StopIteration:
            pass
        except Exception as e:
            rec["verdict"] = "EXC"
            rec["exc"] = f"{type(e).__name__}: {e}"
            rec["tb"] = traceback.format_exc()[-800:]
        rec["p"] = dict(m.p)
        rec["undo_names"] = list(m.doc.UndoNames)[:6]
        rec["hist"] = len(hist)
        if m.seed is not None:
            m.lastSeed = App.Placement(m.seed.Placement)
        rec["t"] = round(time.time() - t0, 3)
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
        log.write(json.dumps(rec, default=str) + "\n")
        log.flush()
        if rec["verdict"] in ("SILENT", "SILENT?", "EXC"):
            try:
                rec["body"] = [(o.Name, o.TypeId, bool(getattr(o, "Suppressed", False)), list(o.State),
                                getattr(getattr(o, "BaseFeature", None), "Name", None),
                                round(o.Shape.Volume, 3) if hasattr(o, "Shape") and not o.Shape.isNull() else None)
                               for o in m.blkBody.Group if o.TypeId.startswith("PartDesign")]
                rec["tip"] = m.blkBody.Tip.Name if m.blkBody.Tip else None
                rec["docs"] = [m.doc.Name, m.blkBody.Document.Name, m.box.Document.Name,
                               [o.Name for o in m.blkBody.Group], [o.Name for o in m.doc.Objects if o.TypeId.startswith("PartDesign")]]
                rec["bodyV"] = round(m.blkBody.Shape.Volume, 3)
            except Exception as e:
                rec["body"] = str(e)
            log.write(json.dumps({"debug": rec.get("step"), "body": rec.get("body"), "tip": rec.get("tip"),
                                  "docs": rec.get("docs"), "bodyV": rec.get("bodyV")}, default=str) + chr(10))
            # Stop the walk at the first finding: later steps would build on a wrong state.
            break
    log.write(json.dumps({"seed": SEED, "summary": counts}) + "\n")
    log.close() if OUT else None


main()
