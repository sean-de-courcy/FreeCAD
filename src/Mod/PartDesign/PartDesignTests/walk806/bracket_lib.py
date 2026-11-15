# realuse.py: a NEW part designed from scratch in the real FreeCAD-CH GUI (Mac lane realuse, ops#673/#640).
# No mouse tool on this Mac, so the "hand" is a macro: it selects what a user would click (Gui.Selection), runs the
# toolbar command, types into the task dialog's widgets and presses OK. Sketch geometry is added in sketch edit mode
# (what the drawing tools produce), constraints one by one; dimension edits go through setDatum in edit mode (what the
# datum dialog does). Every step is timed (wall, incl. GUI settle) and checked against designed, analytic geometry.
import os, re, time, json, math, subprocess, traceback
import FreeCAD as App, FreeCADGui as Gui, Part, Sketcher
from PySide import QtCore, QtGui
V = App.Vector

import tempfile
D = os.environ.get("WALK806_DIR") or tempfile.mkdtemp(prefix="walk806-")
os.makedirs(D + "/shots", exist_ok=True)
DOC = D + "/blocks.FCStd"
LOG = open(D + "/blocks.log", "a", buffering=1)
rows = []
MODALS = []
SLOW = 1.0
PI = math.pi

def log(*a):
    s = time.strftime("%H:%M:%SZ", time.gmtime()) + " " + " ".join(str(x) for x in a)
    LOG.write(s + "\n"); print(s)

def settle():
    for _ in range(3):
        Gui.updateGui(); QtGui.QApplication.processEvents()

def shot(name):
    p = "%s/shots/%02d-%s.png" % (D, len(rows), re.sub(r"\W+", "_", name)[:50])
    try:
        settle(); subprocess.run(["screencapture", "-x", p], timeout=30)
    except Exception as e:
        log("shot failed", e); p = None
    return p

def _watch():
    w = QtGui.QApplication.activeModalWidget()
    if w is not None and not getattr(w, "_ru_seen", False):
        w._ru_seen = True
        texts = [x.text() for x in w.findChildren(QtGui.QLabel) if x.text()][:4]
        p = shot("modal-%d" % len(MODALS))
        MODALS.append(dict(title=w.windowTitle(), cls=type(w).__name__, texts=texts, shot=p))
        log("MODAL", json.dumps(MODALS[-1]))
        QtCore.QTimer.singleShot(300, w.accept if hasattr(w, "accept") else w.close)
WATCH = QtCore.QTimer(); WATCH.timeout.connect(_watch)

def tv():
    return Gui.getMainWindow().findChild(QtGui.QWidget, "TaskView") or Gui.getMainWindow()

def set_spin(objname, value):
    w = tv().findChild(QtGui.QWidget, objname)
    if w is None:
        return False
    try:
        w.setFocus(); w.selectAll()
    except Exception:
        pass
    try:
        w.setProperty("rawValue", value)
    except Exception:
        w.setValue(value)
    settle()
    return True

def press_ok():
    for bb in Gui.getMainWindow().findChildren(QtGui.QDialogButtonBox):
        ok = bb.button(QtGui.QDialogButtonBox.Ok)
        if ok is not None and ok.isVisible() and ok.isEnabled():
            ok.click(); settle(); return "OK"
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog(); settle(); return "closeDialog (no OK button found)"
    return "no dialog"

def widgets_dump():
    out = []
    for w in tv().findChildren(QtGui.QWidget):
        if not w.isVisible() or not w.objectName() or w.objectName().startswith("qt_"):
            continue
        d = type(w).__name__ + ":" + w.objectName()
        if isinstance(w, QtGui.QComboBox):
            d += "[" + "|".join(w.itemText(i) for i in range(w.count())) + "]"
        out.append(d)
    return out

def combo_pick(objname_hint, text_hint):
    for cb in tv().findChildren(QtGui.QComboBox):
        if not cb.isVisible():
            continue
        if objname_hint and objname_hint.lower() not in cb.objectName().lower():
            continue
        for i in range(cb.count()):
            if text_hint.lower() in cb.itemText(i).lower():
                cb.setCurrentIndex(i); settle()
                cb.activated.emit(i); settle()  # what a click sends; setCurrentIndex alone doesn't
                return cb.itemText(i)
    return None

class R:
    def __init__(self):
        self.doc = None; self.body = None; self.part = None
        self.W, self.H, self.L = 80.0, 50.0, 10.0
        self.other_dressup = 0.0     # measured volume change of the non-corner dress-ups (translation invariant)
        self.corner_r = 5.0
        self.have_corner = False
        self.have = set()

    # ---------------- expected geometry -----------------
    def v_expected(self):
        W, H, L = self.W, self.H, self.L
        v = W * H * L
        h = self.have
        if "slot" in h: v -= (12 * 8 + PI * 16) * 3          # slot pocket, depth 3
        if "boss" in h: v += PI * 144 * (30 - L)             # boss above the plate
        if "groove" in h: v -= PI * (144 - 10.5 ** 2) * 3    # groove ring (material only to r 12)
        if "hole" in h: v -= PI * 9 * L                      # hole, through
        if "pattern" in h: v -= PI * 9 * L                   # its pattern copy
        if self.have_corner:
            v -= 4 * (4 - PI) / 4 * self.corner_r ** 2 * L   # 4 vertical corner rounds
        return v + self.other_dressup

    def tip(self):
        return self.part.Tip if self.part is not None else None

    def path(self, obj, sub):
        """(container, subname) a click on obj.sub produces, in the fork's studio model"""
        if obj.TypeId in ("App::Plane", "App::Line", "App::Point"):
            org = [x for x in obj.InList if x.TypeId == "App::Origin"][0]
            b = [x for x in org.InList if x.isDerivedFrom("PartDesign::Body")][0]
            return b.Name, "%s.%s.%s" % (org.Name, obj.Name, sub)
        g = obj.getParentGeoFeatureGroup()
        if g is None:
            return obj.Name, sub
        return g.Name, "%s.%s" % (obj.Name, sub)

    def select(self, items):
        Gui.Selection.clearSelection()
        for (obj, sub) in items:
            c, sn = self.path(obj, sub)
            Gui.Selection.addSelection(self.doc.Name, c, sn)
        settle()
        return [(x.ObjectName, x.SubElementNames) for x in Gui.Selection.getSelectionEx("", 0)]

    def activate_part(self):
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.part); settle()

    def errors(self):
        return [(o.Name, list(o.State)) for o in self.doc.Objects if "Invalid" in o.State or "Error" in o.State]

    def step(self, label, fn, check_volume=True):
        log("BEGIN", label)
        problems = []; nmod = len(MODALS)
        t0 = time.perf_counter()
        try:
            info = fn(problems)
        except Exception:
            info = None; problems.append("EXC " + traceback.format_exc().splitlines()[-1])
            log(traceback.format_exc())
        settle()
        wall = time.perf_counter() - t0
        e = self.errors() if self.doc else []
        if e:
            problems.append("objects in error: %s" % [(n, self.doc.getObject(n).getStatusString()) for n, st in e[:5]])
        vol = None
        if self.part is not None and check_volume:
            sh = self.part.Shape
            vol = sh.Volume
            if not sh.isValid():
                problems.append("tip shape invalid")
            if len(sh.Solids) != 1:
                problems.append("tip has %d solids" % len(sh.Solids))
            if check_volume == "exact":
                ve = self.v_expected()
                if abs(vol - ve) > 1e-6 * max(1, ve):
                    problems.append("WRONG volume %.4f, designed %.4f (d %.4f)" % (vol, ve, vol - ve))
        for m in MODALS[nmod:]:
            problems.append("modal dialog: %s %s" % (m["title"], m["texts"][:2]))
        r = dict(step=label, wall_s=round(wall, 3), slow=wall > SLOW, problems=problems, info=info,
                 volume=round(vol, 4) if vol is not None else None, tip=self.tip().Name if self.part and self.tip() else None)
        if os.environ.get("RU_DUMP"):
            try:
                for o in (self.doc.Objects if self.doc else []):
                    sv = None
                    try:
                        sv = round(o.Shape.Volume, 3) if hasattr(o, "Shape") and not o.Shape.isNull() else None
                    except Exception as e:
                        sv = "ERR %s" % e
                    log("  OBJ", o.Name, o.TypeId, repr(o.Label), list(o.State), sv,
                        "Tip=%s" % getattr(getattr(o, "Tip", None), "Name", None), "In=%s" % [x.Name for x in o.InList][:4])
            except Exception as e:
                log("dump failed", e)
        r["shot"] = shot(label)
        rows.append(r); log("END", json.dumps(r, default=str))
        return r

    # ---------------- sketch helpers -----------------
    def new_sketch(self, select):
        self.selnow = self.select(select)
        before = set(o.Name for o in self.doc.Objects)
        Gui.runCommand("PartDesign_NewSketch"); settle()
        sk = [o for o in self.doc.Objects if o.Name not in before and o.isDerivedFrom("Sketcher::SketchObject")]
        if not sk:
            return None
        sk = sk[0]; sk.recompute()
        log("sketch", sk.Name, "in", [x.Name for x in sk.InList], "sel", self.selnow)
        return sk

    def loc(self, sk, p):
        q = sk.Placement.inverse().multVec(p)
        return V(q.x, q.y, 0)

    def axis_of(self, sk, gaxis):
        """sketch axis (0=x, 1=y) along global axis gaxis, and its sign"""
        q = sk.Placement.Rotation.inverted().multVec(gaxis)
        if abs(abs(q.x) - 1) < 1e-9: return 0, (1 if q.x > 0 else -1)
        if abs(abs(q.y) - 1) < 1e-9: return 1, (1 if q.y > 0 else -1)
        return None, 0

    def draw(self, sk, lines=(), arcs=(), circles=()):
        """global-coordinate geometry -> sketch geometry, auto coincident/tangent at shared ends and H/V on axis lines."""
        g = []
        for (a, b) in lines:
            g.append(Part.LineSegment(self.loc(sk, a), self.loc(sk, b)))
        for (a, m, b) in arcs:
            g.append(Part.ArcOfCircle(self.loc(sk, a), self.loc(sk, m), self.loc(sk, b)))
        for (c, r) in circles:
            g.append(Part.Circle(self.loc(sk, c), V(0, 0, 1), r))
        first = sk.GeometryCount
        sk.addGeometry(g, False)
        ids = list(range(first, first + len(g)))
        nl = len(lines)
        cons = []
        ends = []
        for i in ids[:nl + len(arcs)]:
            for pos in (1, 2):
                ends.append((i, pos, sk.getPoint(i, pos)))
        used = set()
        for x in range(len(ends)):
            for y in range(x + 1, len(ends)):
                (i, pi, p), (j, pj, q) = ends[x], ends[y]
                if i == j or (i, pi) in used or (j, pj) in used or (p - q).Length > 1e-7:
                    continue
                used.add((i, pi)); used.add((j, pj))
                kind = "Tangent" if ((i - first < nl) != (j - first < nl)) else "Coincident"
                cons.append(Sketcher.Constraint(kind, i, pi, j, pj))
        for i in ids[:nl]:
            d = sk.getPoint(i, 2) - sk.getPoint(i, 1)
            if abs(d.y) < 1e-9: cons.append(Sketcher.Constraint("Horizontal", i))
            elif abs(d.x) < 1e-9: cons.append(Sketcher.Constraint("Vertical", i))
        for c in cons:
            sk.addConstraint(c)
        return ids

    def dim(self, sk, name, gaxis, a, b):
        """a, b = (geo, pos) or (-1, 1) root; distance along global axis gaxis, oriented positive."""
        ax, sgn = self.axis_of(sk, gaxis)
        pa = sk.getPoint(*a) if a[0] >= 0 else V(0, 0, 0)
        pb = sk.getPoint(*b) if b[0] >= 0 else V(0, 0, 0)
        val = (pb - pa)[ax]
        if val < 0:
            a, b, val = b, a, -val
        c = Sketcher.Constraint("DistanceX" if ax == 0 else "DistanceY", a[0], a[1], b[0], b[1], val)
        i = sk.addConstraint(c)
        if name:
            sk.renameConstraint(i, name)
        return i

    def close_sketch(self, sk, problems):
        settle()
        info = "%d geo %d cons" % (sk.GeometryCount, sk.ConstraintCount)
        try:
            dof = sk.solve()
            info += " solve=%s" % dof
        except Exception as e:
            problems.append("solve: %s" % e)
        for a in ("FullyConstrained", "MalformedConstraints", "ConflictingConstraints", "RedundantConstraints"):
            if hasattr(sk, a):
                v = getattr(sk, a)
                info += " %s=%s" % (a, v)
                if a == "FullyConstrained" and not v: problems.append("sketch not fully constrained")
                if a != "FullyConstrained" and v: problems.append("%s %s" % (a, v))
        Gui.ActiveDocument.resetEdit(); settle()
        self.doc.recompute(); settle()
        return info

    def face(self, obj, pred):
        best = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if pred(f) and (best is None or f.Area > best[1].Area):
                best = ("Face%d" % i, f)
        return best[0] if best else None

    def top_face(self, obj):
        L = self.L
        return self.face(obj, lambda f: f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMin - L) < 1e-7
                         and abs(f.BoundBox.ZMax - L) < 1e-7 and f.normalAt(0, 0).z > 0.99)

    def feature(self, cmd, typeid, sel):
        self.selnow = self.select(sel)
        before = set(o.Name for o in self.doc.Objects)
        Gui.runCommand(cmd); settle()
        f = [o for o in self.doc.Objects if o.Name not in before and o.TypeId == typeid]
        return f[0] if f else None

    def edges(self, obj, pred):
        return ["Edge%d" % i for i, e in enumerate(obj.Shape.Edges, 1) if pred(e)]

    # ---------------- the session -----------------
    def owners(self, p):
        import PartDesign
        out = []
        for o in self.doc.Objects:
            if o.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer") and o.Base is None:
                try:
                    sc = [b.Name for b in PartDesign.studioScopeOf(o)]
                except Exception as e:
                    sc = "ERR %s" % e
                out.append((o.Name, list(o.State), o.getStatusString()[:60], sc))
                if "Invalid" in o.State:
                    p.append("owner %s Invalid: %s (scope %s)" % (o.Name, o.getStatusString()[:80], sc))
        acts = {}
        for name in ("Std_Undo", "Std_Redo", "Std_Save"):
            a = Gui.Command.get(name)
            acts[name] = a.getShortcut() if a else None
        return "owners %s; shortcuts %s" % (out, acts)

    def go_short(self):
        self.step("new document", self.s_newdoc, check_volume=False)
        self.step("new body", self.s_body, check_volume=False)
        self.step("sketch 1: rectangle 80x50, symmetric, on XY", self.s_sk1, check_volume=False)
        self.step("pad sketch 1, 10 mm", self.s_pad, check_volume="exact")
        self.step("sketch 3 on XZ: boss profile", self.s_sk3, check_volume=False)
        self.have.add("boss")
        self.step("revolve boss 360 about V axis", self.s_revolve, check_volume="exact")
        self.step("chamfer boss top circle 1 mm", lambda p: self.s_dress(p, "chamfer"), check_volume=True)
        self.step("owners after chamfer", self.owners, check_volume=False)
        self.step("recompute", lambda p: (self.doc.recompute(), self.owners(p))[1], check_volume=False)
        self.step("fillet boss/plate junction r2", lambda p: self.s_dress(p, "junction"), check_volume=True)
        self.step("owners after the fillet", self.owners, check_volume=False)

    def go_order(self):
        self.step("new document", self.s_newdoc, check_volume=False)
        self.step("new body", self.s_body, check_volume=False)
        self.step("sketch 1: rectangle 80x50 on XY", self.s_sk1, check_volume=False)
        self.step("pad sketch 1, 10 mm", self.s_pad, check_volume="exact")
        def sk3_studio(p):
            part, self.part = self.part, None   # the studio's own XZ plane (Part 1's origin)
            try:
                return self.s_sk3(p)
            finally:
                self.part = part
        self.step("sketch 3 on the studio's XZ plane: boss profile", sk3_studio, check_volume=False)
        self.have.add("boss")
        self.step("revolve boss", self.s_revolve, check_volume="exact")
        self.step("sketch 2 on pad top face: slot", self.s_sk2, check_volume=False)
        self.have.add("slot")
        self.step("pocket slot 3 mm", self.s_pocket_slot, check_volume="exact")
        def order(p):
            l = [o for o in self.doc.Objects if o.TypeId == "PartDesign::StudioList"][0]
            names = [e.Name for e in l.Entries]
            homes = {o.Name: [x.Name for x in o.InList if x.TypeId == "PartDesign::Body"]
                     for o in self.doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")}
            want = ["Sketch", "Pad", "Sketch001", "Revolution", "Sketch002", "Pocket"]
            if [n for n in names if n in want] != want:
                p.append("ORDER %s (designed %s)" % (names, want))
            return "entries %s; sketch homes %s" % (names, homes)
        self.step("studio list order", order, check_volume=False)

    def go(self):
        if os.environ.get("RU_ORDER"):
            return self.go_order()
        if os.environ.get("RU_SHORT"):
            return self.go_short()
        self.step("new document", self.s_newdoc, check_volume=False)
        self.step("new body", self.s_body, check_volume=False)
        self.step("sketch 1: rectangle 80x50, symmetric, on XY", self.s_sk1, check_volume=False)
        self.step("pad sketch 1, 10 mm", self.s_pad, check_volume="exact")
        self.step("sketch 2 on pad top face: slot (2 lines + 2 tangent arcs)", self.s_sk2, check_volume=False)
        self.have.add("slot")
        self.step("pocket slot 3 mm", self.s_pocket_slot, check_volume="exact")
        self.step("sketch 3 on XZ: boss profile", self.s_sk3, check_volume=False)
        self.have.add("boss")
        self.step("revolve boss 360 about V axis", self.s_revolve, check_volume="exact")
        self.step("sketch 4 on XZ: groove profile", self.s_sk4, check_volume=False)
        self.have.add("groove")
        self.step("groove 360 about V axis", self.s_groove, check_volume="exact")
        self.step("sketch 5 on plate top face: hole r3", self.s_sk5, check_volume=False)
        self.have.add("hole")
        self.step("pocket hole r3 (Through all with THROUGH_ALL, else 40 mm deep)", self.s_hole, check_volume="exact")
        self.have.add("pattern")
        self.step("linear pattern hole, 2 along -Y 30 mm", self.s_pattern, check_volume="exact")
        self.step("fillet 4 vertical corners r5 (lines)", self.s_fil_corner, check_volume="exact")
        self.step("fillet slot rim r1 (tangent chain: lines+arcs)", lambda p: self.s_dress(p, "rim"), check_volume=True)
        self.step("fillet boss/plate junction r2 (circle, concave)", lambda p: self.s_dress(p, "junction"), check_volume=True)
        self.step("chamfer boss top edge + groove upper edge 1 mm (circles)", lambda p: self.s_dress(p, "chamfer"), check_volume=True)
        self.step("check all features and positions", self.s_where, check_volume="exact")
        self.step("edit sketch 1 Width 80 -> 90", lambda p: self.s_datum(p, "Width", 90.0), check_volume="exact")
        self.step("check positions after Width", self.s_where, check_volume="exact")
        self.step("edit sketch 1 Height 50 -> 60", lambda p: self.s_datum(p, "Height", 60.0), check_volume="exact")
        self.step("edit pad length 10 -> 12 in the Pad dialog", self.s_padlen, check_volume="exact")
        self.step("check positions after pad length", self.s_where, check_volume="exact")
        self.step("save as", self.s_save, check_volume=False)
        self.step("close document", self.s_close, check_volume=False)
        self.step("reopen document", self.s_reopen, check_volume="exact")
        self.step("recompute after reopen", lambda p: (self.doc.recompute(), "recomputed %s" % len(self.errors()))[1], check_volume="exact")
        self.step("edit sketch 1 Width 90 -> 100 after reopen", lambda p: self.s_datum(p, "Width", 100.0), check_volume="exact")
        self.step("check positions after reopen edit", self.s_where, check_volume="exact")
        self.step("Cmd+Z: undo the Width edit (100 -> 90)", lambda p: self.s_key(p, "undo", 90.0), check_volume="exact")
        self.step("Cmd+Shift+Z: redo it (90 -> 100)", lambda p: self.s_key(p, "redo", 100.0), check_volume="exact")
        self.step("Cmd+S: save", lambda p: self.s_key(p, "save", None), check_volume=False)

    def s_newdoc(self, p):
        self.doc = App.newDocument("Bracket"); settle()
        return self.doc.Name

    def s_body(self, p):
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Body"); settle()
        b = [o for o in self.doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        self.body = b[0]
        return self.body.Name

    def plane(self, role):
        b = self.part if self.part is not None else self.body
        return [f for f in b.Origin.OriginFeatures if getattr(f, "Role", "") == role][0]

    def s_sk1(self, p):
        sk = self.new_sketch([(self.plane("XY_Plane"), "")])
        if sk is None:
            p.append("no sketch created"); return
        self.sk1 = sk
        w, h = self.W / 2, self.H / 2
        P = [V(-w, -h, 0), V(w, -h, 0), V(w, h, 0), V(-w, h, 0)]
        ids = self.draw(sk, lines=[(P[0], P[1]), (P[1], P[2]), (P[2], P[3]), (P[3], P[0])])
        sk.addConstraint(Sketcher.Constraint("Symmetric", ids[0], 1, ids[1], 2, -1, 1))
        self.dim(sk, "Width", V(1, 0, 0), (ids[0], 1), (ids[0], 2))
        self.dim(sk, "Height", V(0, 1, 0), (ids[1], 1), (ids[1], 2))
        return self.close_sketch(sk, p)

    def s_pad(self, p):
        f = self.feature("PartDesign_Pad", "PartDesign::Pad", [(self.sk1, "")])
        if f is None:
            p.append("no Pad created"); return
        self.pad = f
        ok = set_spin("lengthEdit", self.L)
        if abs(f.Length.Value - self.L) > 1e-9:
            p.append("Length not taken from the dialog"); f.Length = self.L
        r = press_ok(); self.doc.recompute(); settle()
        parts = [o for o in self.doc.Objects if o.isDerivedFrom("PartDesign::Body") and o is not self.body]
        if len(parts) != 1:
            p.append("pad made %d part bodies" % len(parts))
        self.part = parts[0]; self.activate_part()
        return "length box %s; %s; part %s (%s), tip %s" % (ok, r, self.part.Name, self.part.Label, self.tip().Name)

    def s_sk2(self, p):
        fn = self.top_face(self.tip())
        sk = self.new_sketch([(self.tip(), fn)])
        if sk is None:
            p.append("no sketch"); return
        self.sk2 = sk
        z = self.L
        ids = self.draw(sk, lines=[(V(20, 4, z), V(32, 4, z)), (V(32, -4, z), V(20, -4, z))],
                        arcs=[(V(32, -4, z), V(36, 0, z), V(32, 4, z)), (V(20, 4, z), V(16, 0, z), V(20, -4, z))])
        aR, aL = ids[2], ids[3]
        sk.addConstraint(Sketcher.Constraint("Equal", aR, aL))
        i = sk.addConstraint(Sketcher.Constraint("Radius", aR, 4.0)); sk.renameConstraint(i, "SlotR")
        self.dim(sk, "SlotLen", V(1, 0, 0), (aL, 3), (aR, 3))
        self.dim(sk, "SlotX", V(1, 0, 0), (-1, 1), (aL, 3))
        self.dim(sk, "SlotY", V(0, 1, 0), (-1, 1), (aL, 3)) if abs(self.loc(sk, V(20, 0, z))[self.axis_of(sk, V(0, 1, 0))[0]]) > 1e-9 else \
            sk.addConstraint(Sketcher.Constraint("PointOnObject", aL, 3, -1 if self.axis_of(sk, V(0, 1, 0))[0] == 1 else -2))
        return "on %s.%s; placement %s; " % (self.tip().Name, fn, sk.Placement) + self.close_sketch(sk, p)

    def s_pocket_slot(self, p):
        f = self.feature("PartDesign_Pocket", "PartDesign::Pocket", [(self.sk2, "")])
        if f is None:
            p.append("no Pocket created"); return
        self.slot = f
        set_spin("lengthEdit", 3.0)
        if abs(f.Length.Value - 3.0) > 1e-9:
            p.append("Length not taken from the dialog"); f.Length = 3.0
        return press_ok()

    def s_sk3(self, p):
        sk = self.new_sketch([(self.plane("XZ_Plane"), "")])
        if sk is None:
            p.append("no sketch"); return
        self.sk3 = sk
        P = [V(0, 0, 5), V(12, 0, 5), V(12, 0, 30), V(0, 0, 30)]
        ids = self.draw(sk, lines=[(P[0], P[1]), (P[1], P[2]), (P[2], P[3]), (P[3], P[0])])
        ax, _ = self.axis_of(sk, V(0, 0, 1))
        axis_geo = -2 if ax == 1 else -1
        sk.delConstraint([i for i, c in enumerate(sk.Constraints) if c.Type in ("Vertical", "Horizontal") and c.First == ids[3]][0])
        sk.addConstraint(Sketcher.Constraint("PointOnObject", ids[3], 1, axis_geo))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", ids[3], 2, axis_geo))
        self.dim(sk, "BossR", V(1, 0, 0), (ids[0], 1), (ids[0], 2))
        self.dim(sk, "BossBottom", V(0, 0, 1), (-1, 1), (ids[0], 1))
        self.dim(sk, "BossTop", V(0, 0, 1), (-1, 1), (ids[2], 2))
        self.zaxis = "V_Axis" if ax == 1 else "H_Axis"
        return "global Z is sketch %s; " % self.zaxis + self.close_sketch(sk, p)

    def revolve_like(self, p, cmd, typeid, sk):
        f = self.feature(cmd, typeid, [(sk, "")])
        if f is None:
            p.append("no %s created" % typeid); return None, ""
        ra = f.ReferenceAxis
        info = "default axis %s" % ((ra[0].Name, ra[1]) if ra else None)
        if not ra or ra[1] != [self.zaxis]:
            txt = combo_pick("axis", "vertical" if self.zaxis == "V_Axis" else "horizontal")
            info += "; axis combo -> %s" % txt
            if not f.ReferenceAxis or f.ReferenceAxis[1] != [self.zaxis]:
                f.ReferenceAxis = (sk, [self.zaxis]); p.append("axis set by property")
            else:
                info += "; axis taken from combo" 
        if abs(f.Angle.Value - 360) > 1e-9:
            p.append("default angle %s" % f.Angle)
        res = None
        for cb in tv().findChildren(QtGui.QComboBox):
            items = [cb.itemText(i) for i in range(cb.count())]
            if cb.isVisible() and any(t.startswith("Add") for t in items) and any(t.startswith("New") for t in items):
                before = cb.currentText()
                want = "Add" if typeid.endswith("Revolution") else "Remove"
                k = [i for i, t in enumerate(items) if t.startswith(want)]
                if k:
                    cb.setCurrentIndex(k[0]); settle()
                res = "result box %s: %s -> %s" % (cb.objectName(), before, cb.currentText())
        info += "; %s" % res
        r = press_ok(); self.doc.recompute(); settle()
        info += "; state after OK+recompute %s %s" % (list(f.State), f.getStatusString())
        if "Invalid" in f.State:
            f.touch(); self.doc.recompute(); settle()
            info += "; after touch+recompute %s" % list(f.State)
            if "Invalid" not in f.State: p.append("STALE error: Invalid after OK, valid only after a second recompute")
        return f, info + "; " + r

    def s_revolve(self, p):
        f, info = self.revolve_like(p, "PartDesign_Revolution", "PartDesign::Revolution", self.sk3)
        self.rev = f
        return info

    def s_sk4(self, p):
        sk = self.new_sketch([(self.plane("XZ_Plane"), "")])
        if sk is None:
            p.append("no sketch"); return
        self.sk4 = sk
        P = [V(10.5, 0, 20), V(12.5, 0, 20), V(12.5, 0, 23), V(10.5, 0, 23)]
        ids = self.draw(sk, lines=[(P[0], P[1]), (P[1], P[2]), (P[2], P[3]), (P[3], P[0])])
        self.dim(sk, "GrooveIn", V(1, 0, 0), (-1, 1), (ids[0], 1))
        self.dim(sk, "GrooveZ", V(0, 0, 1), (-1, 1), (ids[0], 1))
        self.dim(sk, "GrooveW", V(1, 0, 0), (ids[0], 1), (ids[0], 2))
        self.dim(sk, "GrooveH", V(0, 0, 1), (ids[1], 1), (ids[1], 2))
        return self.close_sketch(sk, p)

    def s_groove(self, p):
        f, info = self.revolve_like(p, "PartDesign_Groove", "PartDesign::Groove", self.sk4)
        self.groove = f
        return info

    def s_sk5(self, p):
        tipo = self.tip()
        fn = self.top_face(tipo)
        sk = self.new_sketch([(tipo, fn)])
        if sk is None:
            p.append("no sketch"); return
        self.sk5 = sk
        ids = self.draw(sk, circles=[(V(-28, 15, self.L), 3.0)])
        i = sk.addConstraint(Sketcher.Constraint("Radius", ids[0], 3.0)); sk.renameConstraint(i, "HoleR")
        self.dim(sk, "HoleX", V(1, 0, 0), (-1, 1), (ids[0], 3))
        self.dim(sk, "HoleY", V(0, 1, 0), (-1, 1), (ids[0], 3))
        return "on %s.%s; " % (tipo.Name, fn) + self.close_sketch(sk, p)

    def s_hole(self, p):
        f = self.feature("PartDesign_Pocket", "PartDesign::Pocket", [(self.sk5, "")])
        if f is None:
            p.append("no Pocket"); return
        self.hole = f
        # The Through-all freeze (found and fixed on Windows, not in lx9) hangs the next step's pattern dialog
        # on the Mac too (lx6 F1, again on lx9): a 40 mm deep pocket from the top face cuts the same hole
        if os.environ.get("THROUGH_ALL"):
            txt = combo_pick("changeMode", "through all")
            if f.Type != "ThroughAll":
                p.append("Type ThroughAll not taken from combo (%s)" % txt); f.Type = "ThroughAll"
            return "type combo -> %s; %s" % (txt, press_ok())
        txt = combo_pick("changeMode", "dimension")
        set_spin("lengthEdit", 40.0)
        if f.Type != "Length" or abs(f.Length.Value - 40) > 1e-9:
            p.append("Type Length 40 not taken from the dialog (%s %s)" % (f.Type, f.Length)); f.Type = "Length"; f.Length = 40.0
        return "type combo -> %s; %s" % (txt, press_ok())

    def s_pattern(self, p):
        f = self.feature("PartDesign_LinearPattern", "PartDesign::LinearPattern", [(self.hole, "")])
        if f is None:
            p.append("no LinearPattern"); return
        self.pat = f
        dump = widgets_dump()
        log("pattern dialog widgets", dump)
        info = ["originals %s" % [o.Name for o in f.Originals], "default dir %s" % (str((f.Direction[0].Name, f.Direction[1])) if f.Direction else None)]
        ax, sgn = self.axis_of(self.sk5, V(0, 1, 0))
        want = "vertical" if ax == 1 else "horizontal"
        t = combo_pick("", want + " sketch axis")
        info.append("dir combo -> %s" % t)
        want_axis = "V_Axis" if ax == 1 else "H_Axis"
        if not f.Direction or f.Direction[1] != [want_axis]:
            f.Direction = (self.sk5, [want_axis]); p.append("direction set by property")
        # occurrences and length boxes: try the usual names
        # ops#783 (fixed on Windows, 9f221e00f7, not in lx9): a raw setValue on the UIntSpinBox writes 2^31 + 2;
        # the count is set through the property instead
        if os.environ.get("RAW_COUNT"):
            w = tv().findChild(QtGui.QWidget, "spinOccurrences")
            t0 = time.perf_counter(); w.setValue(2); settle()
            info.append("raw setValue(2) on the count box (ops#783): %.2f s, Occurrences %s" % (time.perf_counter() - t0, f.Occurrences))
            if f.Occurrences != 2:
                p.append("ops#783: the count box wrote %s" % f.Occurrences); f.Occurrences = 2
        else:
            f.Occurrences = 2; settle(); info.append("occurrences by property (ops#783)")
        mode = tv().findChild(QtGui.QComboBox, "comboMode")
        info.append("dialog mode %s" % (mode.currentText() if mode else None))
        if set_spin("spinSpacing", 30.0):
            info.append("spacing box")
        if f.Occurrences != 2:
            p.append("Occurrences not taken from the dialog (%s)" % f.Occurrences); f.Occurrences = 2
        info.append("Mode %s Offset %s Length %s" % (f.Mode, f.Offset, f.Length))
        if f.Mode == "Spacing" and abs(f.Offset.Value - 30) > 1e-9:
            p.append("Spacing not taken from the dialog (%s)" % f.Offset); f.Offset = 30.0
        info.append(press_ok())
        self.doc.recompute(); settle()
        ys = sorted(round(c[1], 4) for c in self.holes())
        if ys != [-15.0, 15.0]:
            # reverse via the dialog's checkbox
            Gui.ActiveDocument.setEdit(f); settle()
            cb = tv().findChild(QtGui.QCheckBox, "checkReverse")
            if cb is not None:
                cb.click(); settle(); info.append("reverse checkbox")
            else:
                f.Reversed = not f.Reversed; p.append("Reversed set by property")
            info.append(press_ok()); self.doc.recompute(); settle()
            info.append("after reopen+reverse: Mode %s Offset %s Length %s" % (f.Mode, f.Offset, f.Length))
            ys = sorted(round(c[1], 4) for c in self.holes())
            info.append("needed Reverse (sketch +Y maps to global %d)" % sgn)
        if ys != [-15.0, 15.0]:
            p.append("WRONG hole positions y %s" % ys)
        return "; ".join(info)

    def holes(self):
        out = []
        for f in self.part.Shape.Faces:
            s = f.Surface
            if s.__class__.__name__ == "Cylinder" and abs(s.Radius - 3) < 1e-7 and f.BoundBox.ZLength > 1:
                out.append((round(s.Center.x, 4), round(s.Center.y, 4)))
        return sorted(set(out))

    def s_fil_corner(self, p):
        t = self.tip(); W, H, L = self.W, self.H, self.L
        es = self.edges(t, lambda e: e.Curve.__class__.__name__ == "Line" and abs(e.Length - L) < 1e-7
                        and abs(abs(e.Vertexes[0].X) - W / 2) < 1e-7 and abs(abs(e.Vertexes[0].Y) - H / 2) < 1e-7)
        if len(es) != 4:
            p.append("found %d corner edges" % len(es))
        f = self.feature("PartDesign_Fillet", "PartDesign::Fillet", [(t, e) for e in es])
        self.fc = f
        log("fillet sel", self.selnow, "new", f and f.Name, "task", widgets_dump()[-25:])
        if f is None:
            p.append("no Fillet created; new objects: %s" % [(o.Name, o.TypeId) for o in self.doc.Objects][-4:]); return
        def bases():
            return [(o.Name, o.Base[0].Name if o.Base else None, list(o.Base[1]) if o.Base else None)
                    for o in self.doc.Objects if o.TypeId == "PartDesign::Fillet"]
        log("fillet bases at creation", bases())
        set_spin("filletRadius", 5.0)
        if abs(f.Radius.Value - 5) > 1e-9:
            p.append("Radius not taken from the dialog"); f.Radius = 5.0
        n = len(f.Base[1]) if f.Base else -1
        r = press_ok(); self.doc.recompute()
        log("fillet bases after OK", bases())
        p.append("fillet bases %s" % bases())
        self.have_corner = True
        return "%d edges picked, %d taken; %s" % (len(es), n, r)

    def s_dress(self, p, which):
        t = self.tip(); L = self.L
        v0 = self.part.Shape.Volume
        if which == "rim":
            es = self.edges(t, lambda e: abs(e.BoundBox.ZMin - L) < 1e-7 and abs(e.BoundBox.ZMax - L) < 1e-7
                            and e.BoundBox.XMin > 15 and e.BoundBox.XMax < 37 and abs(e.BoundBox.YMax) < 4.1 and abs(e.BoundBox.YMin) < 4.1)
            cmd, tid, box, val, prop, n_exp = "PartDesign_Fillet", "PartDesign::Fillet", "filletRadius", 1.0, "Radius", 4
        elif which == "junction":
            es = self.edges(t, lambda e: e.Curve.__class__.__name__ == "Circle" and abs(e.Curve.Radius - 12) < 1e-7
                            and abs(e.Curve.Center.z - L) < 1e-7)
            cmd, tid, box, val, prop, n_exp = "PartDesign_Fillet", "PartDesign::Fillet", "filletRadius", 2.0, "Radius", 1
        else:
            es = self.edges(t, lambda e: e.Curve.__class__.__name__ == "Circle" and abs(e.Curve.Radius - 12) < 1e-7
                            and (abs(e.Curve.Center.z - 30) < 1e-7 or abs(e.Curve.Center.z - 23) < 1e-7))
            cmd, tid, box, val, prop, n_exp = "PartDesign_Chamfer", "PartDesign::Chamfer", "chamferSize", 1.0, "Size", 2
        info = "picked %s" % es
        if len(es) != n_exp:
            p.append("found %d edges, designed %d" % (len(es), n_exp))
        f = self.feature(cmd, tid, [(t, e) for e in es])
        if f is None:
            p.append("no %s" % tid); return info
        setattr(self, "f_" + which, f)
        set_spin(box, val)
        if abs(getattr(f, prop).Value - val) > 1e-9:
            p.append("%s not taken from the dialog" % prop); setattr(f, prop, val)
        info += "; %s taken; %s" % (len(f.Base[1]) if f.Base else "owner", press_ok())
        self.doc.recompute(); settle()
        dv = self.part.Shape.Volume - v0
        self.other_dressup += dv
        if (which == "junction") != (dv > 0):
            p.append("WRONG volume sign dV %.4f" % dv)
        return info + "; dV %.4f" % dv

    def s_where(self, p):
        t = self.part; W, H, L = self.W, self.H, self.L
        bb = t.Shape.BoundBox
        out = ["bbox %.3f x %.3f x %.3f" % (bb.XLength, bb.YLength, bb.ZLength)]
        if abs(bb.XLength - W) > 1e-6 or abs(bb.YLength - H) > 1e-6 or abs(bb.ZMax - 30) > 1e-6 or abs(bb.ZMin) > 1e-6:
            p.append("WRONG bbox %s (designed %sx%s, z 0..30)" % (out[0], W, H))
        hs = self.holes()
        out.append("holes %s" % hs)
        if hs != [(-28.0, -15.0), (-28.0, 15.0)]:
            p.append("WRONG holes moved: %s (designed (-28,+-15))" % hs)
        slots = sorted(set((round(f.Surface.Center.x, 4), round(f.Surface.Center.y, 4)) for f in t.Shape.Faces
                           if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - 4) < 1e-7))
        out.append("slot arc centres %s" % slots)
        if slots != [(20.0, 0.0), (32.0, 0.0)]:
            p.append("WRONG slot moved: %s (designed (20,0),(32,0))" % slots)
        r5 = [f for f in t.Shape.Faces if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - 5) < 1e-7]
        out.append("corner rounds %d" % len(r5))
        if len(r5) != 4:
            p.append("WRONG corner rounds %d" % len(r5))
        tor = [f for f in t.Shape.Faces if f.Surface.__class__.__name__ == "Toroid"]
        out.append("torus faces %d" % len(tor))
        return "; ".join(out)

    def s_datum(self, p, name, val):
        sk = self.doc.getObject(self.sk1.Name) if self.doc else self.sk1
        Gui.ActiveDocument.setEdit(sk); settle()
        sk.setDatum(name, App.Units.Quantity("%s mm" % val)); settle()
        if name == "Width": self.W = val
        if name == "Height": self.H = val
        info = self.close_sketch(sk, p)
        return info

    def s_padlen(self, p):
        pad = self.doc.getObject(self.pad.Name)
        Gui.ActiveDocument.setEdit(pad); settle()
        ok = set_spin("lengthEdit", 12.0)
        if abs(pad.Length.Value - 12) > 1e-9:
            p.append("Length not taken from the dialog"); pad.Length = 12.0
        r = press_ok(); self.doc.recompute(); settle()
        self.L = 12.0
        return "box %s; %s" % (ok, r)

    def s_key(self, p, what, width):
        from PySide6 import QtTest
        win = Gui.getMainWindow().windowHandle()
        Gui.getMainWindow().activateWindow(); settle()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.part); settle()
        before = (list(self.doc.UndoNames)[:2], list(self.doc.RedoNames)[:2], os.path.getmtime(DOC))
        key = {"undo": (QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier),
               "redo": (QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier),
               "save": (QtCore.Qt.Key_S, QtCore.Qt.ControlModifier)}[what]
        t0 = time.perf_counter()
        QtTest.QTest.keyClick(win, key[0], key[1]); settle()
        dt = time.perf_counter() - t0
        self.doc.recompute(); settle()
        after = (list(self.doc.UndoNames)[:2], list(self.doc.RedoNames)[:2], os.path.getmtime(DOC))
        if width is not None:
            self.W = width
        if what == "save" and after[2] == before[2]:
            p.append("Cmd+S did not save (mtime unchanged)")
        if what in ("undo", "redo") and before[:2] == after[:2]:
            p.append("%s key changed no undo/redo list" % what)
        return "key %.3f s; undo %s redo %s -> undo %s redo %s" % (dt, before[0], before[1], after[0], after[1])

    def s_save(self, p):
        if os.path.exists(DOC): os.remove(DOC)
        self.doc.saveAs(DOC)
        return os.path.getsize(DOC)

    def s_close(self, p):
        self.names = dict(sk1=self.sk1.Name, pad=self.pad.Name, body=self.body.Name, part=self.part.Name)
        App.closeDocument(self.doc.Name); settle()
        self.doc = None; self.body = None; self.part = None; self.part = None
        return "closed"

    def s_reopen(self, p):
        self.doc = App.openDocument(DOC); settle()
        self.body = self.doc.getObject(self.names["body"])
        self.sk1 = self.doc.getObject(self.names["sk1"]); self.pad = self.doc.getObject(self.names["pad"])
        self.part = self.doc.getObject(self.names["part"]); self.activate_part()
        tch = [o.Name for o in self.doc.Objects if "Touched" in o.State]
        if tch:
            p.append("touched after open: %s" % tch[:8])
        return "opened; touched %d" % len(tch)

def main():
    try:
        Gui.getMainWindow().showMaximized(); Gui.getMainWindow().raise_(); Gui.getMainWindow().activateWindow(); settle()
        WATCH.start(300)
        Gui.activateWorkbench("PartDesignWorkbench"); settle()
        log("=== start pid %d" % os.getpid())
        BLOCKS()
    except Exception:
        log("FATAL", traceback.format_exc())
    finally:
        json.dump(dict(rows=rows, modals=MODALS), open(D + "/blocks.json", "w"), indent=1, default=str)
        log("=== done")
        for d in list(App.listDocuments()):
            try:
                App.closeDocument(d)
            except Exception:
                pass
        QtCore.QTimer.singleShot(500, lambda: Gui.getMainWindow().close())
        QtCore.QTimer.singleShot(3000, lambda: os._exit(0))

