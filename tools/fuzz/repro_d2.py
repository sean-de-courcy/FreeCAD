# repro_d2.py (ops#640, scout 2, found by D+'s jump check): in the D+ studio (designed geometry, fuzzplus.Studio at its
# defaults), Tab.Length 5 -> 3.08 and a topology change of TabSk (its rectangle's bottom edge split in two, the sketch
# redrawn), made together and recomputed once, turn TabChamfer red with missing edge references. Either edit alone, or
# both with a recompute in between, keeps it green. A plain sketch redraw (no topology change) is fine too.
# (A bare plate + tab + chamfer doesn't reproduce it: the studio's later features are needed.)
# Run: FreeCADCmd tools/fuzz/repro_d2.py   (prints D2 lines)
import os, sys
os.environ.setdefault("FUZZ_OUT", os.path.join(os.environ.get("TMPDIR", "/tmp"), "fuzz-d2"))
os.environ["FUZZ_NOMAIN"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fuzzplus as F
import FreeCAD as App


def fresh():
    d = App.newDocument("D2"); F.Studio(d).build(); F.PartDesign.studioList(d, True); d.recompute(); return d


def red(d):
    return sorted(o.Name for o in d.Objects if "Invalid" in o.State or "Error" in o.State)


def split(d):
    sk = d.getObject("TabSk"); v = F.sketchVals(sk); sk.deleteAllGeometry(); F.drawSketch(sk, v, "split")


for mode in ("split alone", "length; recompute; split", "length + split, one recompute"):
    d = fresh()
    if mode != "split alone":
        d.getObject("Tab").Length = 3.08
        if mode.startswith("length;"):
            d.recompute()
    split(d)
    d.recompute()
    r = red(d)
    print("D2 %-30s red %s %s" % (mode, r, d.getObject("TabChamfer").getStatusString()[:160] if r else ""))
    App.closeDocument(d.Name)
