# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#806, GUI reproducer from the Mac walk on lx10 (block B). Run in the GUI:
#     FREECAD_USER_HOME=<abs dir> RIBH=3 FreeCAD <this file>      (it quits by itself)
# It builds a designed bracket from scratch with the GUI commands a user clicks (bracket_lib.py, the
# walk's macro: selection + toolbar command + task dialog fields + OK):
# - an 80 x 50 x 10 plate;
# - a slot pocket 3 deep on its top face (two lines + two tangent arcs, centres x 20 and 32, r 4);
# - a boss r 12 revolved from an XZ profile to z 30;
# - a fillet r 1 on the slot's rim (z 10) and a fillet r 2 on the boss/plate junction circle (r 12, z 10).
# Then it rolls the studio's bar back to the slot pocket, adds a rib in the slot there (sketch on the slot
# floor z 7, x 25..27, y -5..5, Pad RIBH), and rolls to end.
# Expected (Onshape keeps a fillet on an edge the insert doesn't touch): every feature valid; the junction
# fillet still rounds its circle (no edge of r 12 left at z 10, a torus face of the r 2 round).
# Found on lx10: RIBH=3 (flush with the top) -> the junction fillet fails, "a picked edge is not found"
# (part 1); RIBH=2 (top on the rim fillet's tangent line z 9) -> SIGSEGV in OCCT (part 2); 1, 2.5, 3.5 clean
# in the full walk bracket. On the Mac (lx10 + ops#804): h 1 KEPT 2 of 2, h 3 LOST 2 of 2, h 2 SIGSEGV. The result line: "RESULT806 h=<h> KEPT|LOST errors=[...]" on stdout and in
# <WALK806_DIR>/run806.log.
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bracket_lib.py")).read())
import PartDesign

def shot(name):  # no screenshots in the reproducer
    return None

VOID = []

def press_ok():
    """OK on the task dialog by its button, as a click (the Tasks panel brought forward, up to 3 s for
    the button to show). A dialog closed any other way doesn't build what OK builds: the run is VOID."""
    t = time.time()
    while time.time() - t < 3.0:
        for dock in Gui.getMainWindow().findChildren(QtGui.QDockWidget):
            if dock.objectName() == "Tasks":
                dock.show(); dock.raise_()
        settle()
        for bb in Gui.getMainWindow().findChildren(QtGui.QDialogButtonBox):
            ok = bb.button(QtGui.QDialogButtonBox.Ok)
            if ok is not None and ok.isVisible() and ok.isEnabled():
                ok.click(); settle(); return "OK"
    VOID.append("no OK button")
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog(); settle()
    return "no OK button (VOID)"

H = float(os.environ.get("RIBH", "3"))

class B806(R):
    def new_sketch(self, select):
        # the GUI may not be ready for a face pick right after a recompute: settle and retry
        for k in range(5):
            sk = R.new_sketch(self, select)
            if sk is not None:
                return sk
            log("new sketch: none, retry %d; selection %s" % (k + 1, Gui.Selection.getSelectionEx("", 0) and
                [(x.ObjectName, x.SubElementNames) for x in Gui.Selection.getSelectionEx("", 0)]))
            t = time.time()
            while time.time() - t < 1.0:
                settle()
        return None

    def go(self):
        self.step("new document", self.s_newdoc, check_volume=False)
        self.step("new body", self.s_body, check_volume=False)
        self.step("plate sketch", self.s_sk1, check_volume=False)
        self.step("pad 10", self.s_pad, check_volume="exact")
        self.step("slot sketch", self.s_sk2, check_volume=False); self.have.add("slot")
        self.step("slot pocket 3", self.s_pocket_slot, check_volume="exact")
        self.step("boss profile", self.s_sk3, check_volume=False); self.have.add("boss")
        self.step("revolve boss", self.s_revolve, check_volume="exact")
        self.step("rim fillet r1", lambda p: self.s_dress(p, "rim"), check_volume=True)
        self.step("junction fillet r2", lambda p: self.s_dress(p, "junction"), check_volume=True)
        self.step("rib inserted after the slot pocket", self.s_rib, check_volume=False)

    def s_rib(self, p):
        doc = self.doc
        PartDesign.rollStudioTo(doc, self.slot); doc.recompute(); settle()
        tip = doc.getObject(self.part.Name).Tip
        fn = self.face(tip, lambda f: f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMin - 7) < 1e-7
                       and abs(f.BoundBox.ZMax - 7) < 1e-7)
        sk = self.new_sketch([(tip, fn)])
        self.draw(sk, lines=[(V(25, -5, 7), V(27, -5, 7)), (V(27, -5, 7), V(27, 5, 7)),
                             (V(27, 5, 7), V(25, 5, 7)), (V(25, 5, 7), V(25, -5, 7))])
        self.close_sketch(sk, [])
        f = self.feature("PartDesign_Pad", "PartDesign::Pad", [(sk, "")])
        set_spin("lengthEdit", H)
        if abs(f.Length.Value - H) > 1e-9:
            f.Length = H
        press_ok(); doc.recompute(); settle()
        PartDesign.rollStudioToEnd(doc); doc.recompute(); settle()
        errs = [(o.Label, o.getStatusString()[:80]) for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
        L = self.L
        left = [e for e in self.part.Shape.Edges if e.Curve.__class__.__name__ == "Circle"
                and abs(e.Curve.Radius - 12) < 1e-7 and abs(e.Curve.Center.z - L) < 1e-7]
        res = "VOID (a dialog's OK button never showed: rerun)" if VOID else ("KEPT" if not errs and not left else "LOST")
        line = "RESULT806 h=%s %s errors=%s junction circle edges left=%d" % (H, res, errs, len(left))
        log(line); print(line, flush=True)
        return line

def main806():
    try:
        mw = Gui.getMainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow(); settle()
        WATCH.start(300)
        Gui.activateWorkbench("PartDesignWorkbench"); settle()
        B806().go()
    except Exception:
        log("FATAL", traceback.format_exc())
    finally:
        QtCore.QTimer.singleShot(500, lambda: os._exit(0))

LOG = open(D + "/run806.log", "a", buffering=1)
QtCore.QTimer.singleShot(3000, main806)
