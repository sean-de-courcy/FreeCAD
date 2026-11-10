# ops#654: tool once, apply per part. A leader Pocket in A computes the tool; B gets a generic applier
# (Python FeatureSubtractivePython applying the leader's AddSubShape); C gets today's sibling (a clone).
import os, sys, traceback, math
sys.path.insert(0, r"D:\CustomFreeCAD\work\standby-a\mods")
import FreeCAD as App
import Part, PartDesign
import proj654
from PartDesignTests.TestStudio import pad, sketch, xyPlane

V = App.Vector
OUT = r"D:\CustomFreeCAD\work\standby-a\applier.log"
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def vol(o):
    return round(o.Shape.Volume, 3)


def facesAt(shape, z, nz=-1):
    """(index, mapped name) of planar faces at height z facing up (the cut's floor)."""
    out = []
    for i, f in enumerate(shape.Faces, 1):
        try:
            if f.Surface.__class__.__name__ == "Plane" and abs(f.CenterOfMass.z - z) < 1e-6 \
                    and abs(abs(f.normalAt(0, 0).z) - 1) < 1e-9 and f.Area < 99:
                out.append((f"Face{i}", round(f.Area, 3), shape.getElementMappedName(f"Face{i}")))
        except Exception as e:
            out.append((f"Face{i}", "?", repr(e)))
    return out


def studio(doc, heights=None):
    S = doc.addObject("App::Part", "S")
    out = []
    for name, x in (("A", 0), ("B", 20), ("C", 40)):
        b = doc.addObject("PartDesign::Body", name)
        S.addObject(b)
        pad(b, name + "Pad", sketch(b, name + "Sk", xyPlane(b), (x, 0, x + 10, 10)), 10)
        out.append(b)
    doc.recompute()
    return S, out


def applier(body, name, tool, op="Cut"):
    st = body.newObject("PartDesign::FeatureSubtractivePython" if op != "Fuse" else "PartDesign::FeatureAdditivePython", name)
    proj654.Applier(st)
    st.Tool = tool
    st.Op = op
    body.Tip = st
    return st


def run():
    doc = App.newDocument("ap")
    doc.UndoMode = 1
    S, (A, B, C) = studio(doc)
    sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 45, 8), z=10)  # over A (x5..10), B (whole), C (x40..45)
    cut = A.newObject("PartDesign::Pocket", "Cut")
    cut.Profile = sk
    cut.Type = "Length"
    cut.Length = 3
    doc.recompute()
    ap = applier(B, "CutB", cut)
    [sib] = PartDesign.makeSiblings(cut, [C])
    doc.recompute()
    log("states", cut.State, ap.State, sib.State, "|", ap.getStatusString())
    log("volumes A B C", vol(A), vol(B), vol(C), "want 910 820 910")
    if len(B.Shape.Solids) != 2:
        log("B solids", len(B.Shape.Solids))
    nA = facesAt(A.Shape, 7)
    nB = facesAt(B.Shape, 7)
    nC = facesAt(C.Shape, 7)
    log("floor names A (leader):", nA)
    log("floor names B (applier):", nB)
    log("floor names C (clone):", nC)
    cut.Length = 5
    doc.recompute()
    log("after Length 5: volumes", vol(A), vol(B), vol(C), "want 850 700 850")
    mA, mB, mC = facesAt(A.Shape, 5), facesAt(B.Shape, 5), facesAt(C.Shape, 5)
    log("floor names A:", mA)
    log("floor names B:", mB)
    log("floor names C:", mC)
    log("stable under edit: A", [x[2] for x in nA] == [x[2] for x in mA], "B", [x[2] for x in nB] == [x[2] for x in mB],
        "C", [x[2] for x in nC] == [x[2] for x in mC])
    log("distinct per part (A vs B vs C):", len({str(x[2]) for x in mA + mB + mC}) == len(mA + mB + mC))
    # a later feature in B referencing the applier's floor face survives the leader's edit?
    # Undo/redo through the applier
    doc.openTransaction("e")
    cut.Length = 4
    doc.commitTransaction()
    doc.recompute()
    doc.undo()
    doc.recompute()
    log("undo: B", vol(B), "want 700")
    # save and reopen (the Python proxy imports from mods)
    path = r"D:\CustomFreeCAD\work\standby-a\files\applier.FCStd"
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    doc.getObject("Cut").Length = 3
    doc.recompute()
    log("reopen edit: B", vol(doc.getObject("B")), "want 820", doc.getObject("CutB").State)
    App.closeDocument(doc.Name)

    # Up to first / up to face: A has an overhang (base z0..3, pillar x0..1, roof z6..10); B solid
    for mode in ("UpToFirst", "UpToFace"):
        doc = App.newDocument("up")
        S = doc.addObject("App::Part", "S")
        A = doc.addObject("PartDesign::Body", "A"); S.addObject(A)
        pad(A, "Base", sketch(A, "BaseSk", xyPlane(A), (0, 0, 10, 10)), 3)
        pad(A, "Pillar", sketch(A, "PilSk", xyPlane(A), (0, 0, 1, 10), z=3), 3)
        roof = pad(A, "Roof", sketch(A, "RoofSk", xyPlane(A), (0, 0, 10, 10), z=6), 4)
        B = doc.addObject("PartDesign::Body", "B"); S.addObject(B)
        pad(B, "BPad", sketch(B, "BSk", xyPlane(B), (20, 0, 30, 10)), 10)
        C = doc.addObject("PartDesign::Body", "C"); S.addObject(C)
        pad(C, "CPad", sketch(C, "CSk", xyPlane(C), (40, 0, 50, 10)), 10)
        doc.recompute()
        a0, b0, c0 = vol(A), vol(B), vol(C)
        sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 45, 8), z=10)
        cut = A.newObject("PartDesign::Pocket", "Cut")
        cut.Profile = sk
        cut.Type = mode
        if mode == "UpToFace":
            under = [f"Face{i}" for i, f in enumerate(roof.Shape.Faces, 1)
                     if abs(f.CenterOfMass.z - 6) < 1e-6 and f.normalAt(0, 0).z < -0.5]
            cut.UpToFace = (roof, under)
        doc.recompute()
        ap = applier(B, "CutB", cut)
        [sib] = PartDesign.makeSiblings(cut, [C])
        doc.recompute()
        log("")
        log(mode + ": leader", cut.getStatusString(), "| removed A", round(a0 - vol(A), 3),
            "| B (applier, the leader's tool)", round(b0 - vol(B), 3), ap.getStatusString(),
            "| C (clone, its own tool)", round(c0 - vol(C), 3), sib.getStatusString())
        App.closeDocument(doc.Name)
    log("  A's cut stops at the roof's underside (z 6): 5x6x4 = 120; the leader's tool on B: 10x6x4 = 240;"
        " B through by its own faces would be 600; C 5x6xdepth")

    # Merge after an applier: two faces whose names are the same string in one shape
    doc = App.newDocument("mg")
    S, (A, B, C) = studio(doc)
    sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 25, 8), z=10)
    cut = A.newObject("PartDesign::Pocket", "Cut")
    cut.Profile = sk
    cut.Type = "Length"
    cut.Length = 3
    doc.recompute()
    applier(B, "CutB", cut)
    doc.recompute()
    br = B.newObject("PartDesign::Pad", "Bridge")
    br.Profile = sketch(B, "BrSk", xyPlane(B), (9, 0, 21, 1), z=0)
    br.Length = 1
    B.Tip = br
    doc.recompute()
    try:
        m = PartDesign.makeMerge(br, [A])
        doc.recompute()
        log("")
        log("merge A into B:", m.getStatusString(), "volume", vol(B), "want", 910 + 910 + 12 - 2)
        log("  floors in the merged shape:", facesAt(B.Shape, 7))
    except Exception as e:
        log("merge refused:", e)
    App.closeDocument(doc.Name)

    # Hole: a leader Hole in A on two circles (one over A, one over B), an applier in B
    doc = App.newDocument("hole")
    S, (A, B, C) = studio(doc)
    hs = sketch(A, "HoleSk", xyPlane(A), z=10)
    hs.addGeometry(Part.Circle(V(7, 5, 0), V(0, 0, 1), 1))
    hs.addGeometry(Part.Circle(V(25, 5, 0), V(0, 0, 1), 1))
    hole = A.newObject("PartDesign::Hole", "Hole")
    hole.Profile = hs
    hole.Diameter = 2
    hole.Depth = 3
    hole.DepthType = "Dimension"
    hole.DrillPoint = "Flat"
    hole.Threaded = False
    doc.recompute()
    ap = applier(B, "HoleB", hole)
    doc.recompute()
    want = round(1000 - math.pi * 3, 3)
    log("")
    log("Hole: A", vol(A), "B", vol(B), "want", want, "|", hole.getStatusString(), ap.getStatusString())
    App.closeDocument(doc.Name)


try:
    run()
except Exception:
    log("EXCEPTION " + traceback.format_exc())
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
os._exit(0)
