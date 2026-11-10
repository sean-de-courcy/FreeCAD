# ops#654: does a PartDesign Pocket outside every Body (a studio-level owner) compute its tool?
import os, sys, traceback
sys.path.insert(0, r"D:\CustomFreeCAD\work\standby-a\mods")
import FreeCAD as App
import Part, PartDesign
import proj654
from PartDesignTests.TestStudio import pad, sketch, xyPlane

L = []
def log(*a):
    L.append(" ".join(str(x) for x in a))

def v(s):
    try:
        return round(s.Volume, 3)
    except Exception as e:
        return repr(e)

try:
    for mode in ("Length", "ThroughAll", "UpToFace", "TwoLengths"):
        doc = App.newDocument("own")
        S = doc.addObject("App::Part", "S")
        A = doc.addObject("PartDesign::Body", "A"); S.addObject(A)
        pad(A, "Base", sketch(A, "BaseSk", xyPlane(A), (0, 0, 10, 10)), 3)
        pad(A, "Pillar", sketch(A, "PilSk", xyPlane(A), (0, 0, 1, 10), z=3), 3)
        roof = pad(A, "Roof", sketch(A, "RoofSk", xyPlane(A), (0, 0, 10, 10), z=6), 4)
        B = doc.addObject("PartDesign::Body", "B"); S.addObject(B)
        pad(B, "BPad", sketch(B, "BSk", xyPlane(B), (20, 0, 30, 10)), 10)
        doc.recompute()
        sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 25, 8), z=10)
        own = doc.addObject("PartDesign::Pocket", "Own")
        S.addObject(own)
        own.Profile = sk
        own.Type = mode
        own.Length = 3
        if mode == "UpToFace":
            under = [f"Face{i}" for i, f in enumerate(roof.Shape.Faces, 1)
                     if abs(f.CenterOfMass.z - 6) < 1e-6 and f.normalAt(0, 0).z < -0.5]
            own.UpToFace = (roof, under)
        doc.recompute()
        steps = []
        for b in (A, B):
            st = b.newObject("PartDesign::FeatureSubtractivePython", "St" + b.Name)
            proj654.Applier(st)
            st.Tool = own
            b.Tip = st
            steps.append(st)
        doc.recompute()
        log(f"{mode}: owner status {own.getStatusString()!r} | tool volume {v(own.AddSubShape)}"
            f" | A {v(A.Shape)} B {v(B.Shape)} | steps {[s.getStatusString() for s in steps]}")
        App.closeDocument(doc.Name)
    log("tool volumes expected: Length 20x6x3=360; UpToFace (z 6) 20x6x4=480; TwoLengths 360+")
except Exception:
    log("EXCEPTION " + traceback.format_exc())
with open(r"D:\CustomFreeCAD\work\standby-a\owner.log", "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
os._exit(0)
