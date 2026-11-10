# ops#654 bake-off, probe C1: (b) studio feature outside the Bodies vs (c) the leader stays in a Body.
# Designed geometry only. Studio S (App::Part) with three 10x10x10 boxes: A at x 0..10, B at x 20..30,
# C at x 40..50 (y 0..10, z 0..10), each 1000. A cut sketch in A on z=10 over x 5..25, y 2..8 straddles
# A and B: a 3 deep cut removes 5*6*3 = 90 from each part it acts on (910).
import os, sys, traceback, tempfile
import FreeCAD as App
import Part
import PartDesign
from PartDesignTests.TestStudio import pad, rect, sketch, xyPlane, inside

V = App.Vector
OUT = os.environ.get("BAKEOFF_OUT", r"D:\CustomFreeCAD\work\standby-a\bakeoff.log")
FILES = r"D:\CustomFreeCAD\work\standby-a\files"
lines = []
fails = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))


def vol(b):
    try:
        return round(b.Shape.Volume, 4)
    except Exception:
        return None


def solids(b):
    try:
        return len(b.Shape.Solids)
    except Exception:
        return None


def check(name, got, want, tol=1e-4):
    ok = got is not None and abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    log(("  OK   " if ok else "  FAIL ") + f"{name}: got {got}, want {want}")
    if not ok:
        fails.append(f"{current}: {name}: got {got}, want {want}")
    return ok


def status(o):
    try:
        return f"{o.Name} state={o.State} why={o.getStatusString()!r}"
    except Exception as e:
        return f"<{e}>"


current = ""


def case(fn):
    global current
    current = fn.__name__
    log("")
    log("=== " + fn.__name__ + ": " + (fn.__doc__ or "").strip().splitlines()[0])
    try:
        fn()
    except Exception:
        log("  EXCEPTION " + traceback.format_exc().replace("\n", "\n    "))
        fails.append(f"{current}: exception")
    for d in list(App.listDocuments().values()):
        try:
            App.closeDocument(d.Name)
        except Exception:
            pass


def studio3(doc, with_c=True):
    S = doc.addObject("App::Part", "S")
    bodies = []
    for name, x in (("A", 0), ("B", 20), ("C", 40))[: 3 if with_c else 2]:
        b = doc.addObject("PartDesign::Body", name)
        b.Label = name
        S.addObject(b)
        sk = sketch(b, name + "Sk", xyPlane(b), (x, 0, x + 10, 10))
        pad(b, name + "Pad", sk, 10)
        bodies.append(b)
    doc.recompute()
    return S, bodies


def cutIn(body, name, r, z=10, length=3):
    sk = sketch(body, name + "Sk", xyPlane(body), r, z=z)
    p = body.newObject("PartDesign::Pocket", name)
    p.Profile = sk
    p.Type = "Length"
    p.Length = length
    return sk, p


def newdoc(name):
    d = App.newDocument(name)
    d.UndoMode = 1
    return d


# ------------------------------------------------------------------------------------------- (c)
def c1_two_parts_and_other_only():
    """(c) one cut acting on A and B, then on B only (report 21), then on C only (sketch in A)."""
    doc = newdoc("c1")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    n = doc.recompute()
    log("  recomputed", n, status(sib))
    check("A two parts", vol(A), 910)
    check("B two parts", vol(B), 910)
    check("C untouched", vol(C), 1000)
    # Report 21: leave the home part out. Today's nearest flag: the leader Suppressed (it passes its
    # base through); the follower's Suppressed is its own, so it still cuts
    cut.Suppressed = True
    doc.recompute()
    log("  leader suppressed:", status(cut), "|", status(sib))
    check("A left out (leader passes through)", vol(A), 1000)
    check("B still cut by the follower", vol(B), 910)
    # Another part only, the sketch's part not touched: C only
    sk2, cut2 = cutIn(A, "CutC", (44, 2, 46, 8))
    doc.recompute()
    log("  leader on A misses A:", status(cut2))
    [sibC] = PartDesign.makeSiblings(cut2, [C])
    cut2.Suppressed = True
    doc.recompute()
    check("C cut by the follower only", vol(C), 1000 - 2 * 6 * 3)
    check("A unchanged", vol(A), 1000)
    log("  ", status(cut2), "|", status(sibC))


def c2_edit_undo_redo():
    """(c) edit of the leader, undo and redo of the edit, of making the follower, of a delete."""
    doc = newdoc("c2")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    doc.openTransaction("siblings")
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.commitTransaction()
    doc.recompute()
    doc.openTransaction("edit")
    cut.Length = 5
    doc.commitTransaction()
    n = doc.recompute()
    log("  edit recomputed", n)
    check("A after edit 5", vol(A), 850)
    check("B follows the edit", vol(B), 850)
    doc.undo()
    doc.recompute()
    check("A undo", vol(A), 910)
    check("B undo", vol(B), 910)
    doc.redo()
    doc.recompute()
    check("A redo", vol(A), 850)
    check("B redo", vol(B), 850)
    doc.undo()
    doc.undo()  # the follower's creation
    doc.recompute()
    check("undo siblings: follower gone", len(PartDesign.siblingsOf(cut)), 0)
    check("B uncut after undo", vol(B), 1000)
    doc.redo()
    doc.recompute()
    sibs = PartDesign.siblingsOf(cut)
    check("redo siblings: follower back", len(sibs), 1)
    check("B cut after redo", vol(B), 910)
    # Delete of the studio feature: leader and follower in one transaction
    doc.openTransaction("delete")
    for s in sibs:
        B.removeObject(s)
        doc.removeObject(s.Name)
    A.removeObject(cut)
    doc.removeObject(cut.Name)
    doc.commitTransaction()
    doc.recompute()
    check("delete fan-out: A", vol(A), 1000)
    check("delete fan-out: B", vol(B), 1000)
    doc.undo()
    doc.recompute()
    cut = doc.getObject("Cut")
    check("undo delete: A", vol(A), 910)
    check("undo delete: B", vol(B), 910)
    check("undo delete: link back", len(PartDesign.siblingsOf(cut)) if cut else None, 1)


def c3_delete_leader_only():
    """(c) delete of the leader alone, and of its home part (Delete part feature; and the Body)."""
    doc = newdoc("c3")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    # Delete part on the home part, after the cut (Onshape: a Delete part feature)
    dp = PartDesign.deletePart(A)
    doc.recompute()
    log("  after deletePart(A):", status(dp), "|", status(sib))
    check("A deleted (empty)", vol(A) or 0.0, 0.0)
    check("B keeps its cut", vol(B), 910)
    cut.Length = 4  # edit the leader of a deleted part
    doc.recompute()
    check("B follows an edit of a leader whose part is deleted", vol(B), 1000 - 5 * 6 * 4)
    A.removeObject(dp)
    doc.removeObject(dp.Name)
    doc.recompute()
    # Delete the leader alone: what happens to the follower
    A.removeObject(cut)
    doc.removeObject(cut.Name)
    r = doc.recompute()
    log("  leader deleted:", status(sib), "SiblingOf=", sib.SiblingOf, "expr=", sib.ExpressionEngine)
    log("  B volume", vol(B))
    # Delete the home Body itself (FreeCAD's delete of a Body with its sketch)
    doc2 = newdoc("c3b")
    S, (A, B, C) = studio3(doc2)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc2.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc2.recompute()
    for o in list(A.Group):
        if o not in (A.Origin,):
            pass
    names = [o.Name for o in A.Group]
    doc2.removeObject(A.Name)
    for nm in names:
        if doc2.getObject(nm):
            doc2.removeObject(nm)
    doc2.recompute()
    log("  home Body removed:", status(sib), "Profile=", sib.Profile, "SiblingOf=", sib.SiblingOf)
    log("  B volume", vol(B))


def c4_reorder_rollback():
    """(c) reorder of the leader across a later feature of the follower's part, and roll-back."""
    doc = newdoc("c4")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    fsk = sketch(B, "FillSk", xyPlane(B), (20, 2, 25, 8), z=7)
    fill = pad(B, "Fill", fsk, 3)
    doc.recompute()
    check("B: cut then fill", vol(B), 1000)
    seq = [o.Name for o in PartDesign.studioSequence(S)]
    log("  sequence", seq)
    # Onshape: drag the cut below Fill: B = 910 (cut after fill). Today's drag moves one Body's rows
    try:
        PartDesign.moveInStudio(S, [cut], fill)
        doc.recompute()
        log("  leader alone moved; sequence", [o.Name for o in PartDesign.studioSequence(S)])
        check("B after moving the leader alone (silent if 1000)", vol(B), 910)
    except Exception as e:
        log("  moveInStudio(leader) refused:", e)
    # Fan-out: the follower moved too
    try:
        PartDesign.moveInStudio(S, [sib], fill)
        doc.recompute()
        log("  follower moved too; sequence", [o.Name for o in PartDesign.studioSequence(S)])
        check("B after fan-out drag", vol(B), 910)
        check("A after fan-out drag", vol(A), 910)
    except Exception as e:
        log("  moveInStudio(follower) refused:", e)
    # Roll-back to the leader, then above it
    PartDesign.rollStudioTo(S, cut)
    doc.recompute()
    log("  rolled to leader: tips", A.Tip.Name, B.Tip.Name, "| holds sib", B.holds(sib) if hasattr(B, "holds") else "?")
    log("  A", vol(A), "B", vol(B), "| B.Tip vol", vol(B.Tip), "| B state", B.State, "| B group", [o.Name for o in B.Group])
    log("  bases", [(o.Name, o.BaseFeature.Name if getattr(o, "BaseFeature", None) else None, vol(o)) for o in B.Group if hasattr(o, "BaseFeature")])
    PartDesign.rollStudioTo(S, fill)
    doc.recompute()
    log("  rolled to Fill: tips", A.Tip.Name, B.Tip.Name, "A", vol(A), "B", vol(B), "| B.Tip vol", vol(B.Tip), "| B state", B.State)
    check("rolled above the cut: B is 1000", vol(B), 1000)
    PartDesign.rollStudioToEnd(S)
    doc.recompute()
    check("end: B", vol(B), 910)


def c5_suppress():
    """(c) suppress of the studio feature: leader and follower together, and the leader alone."""
    doc = newdoc("c5")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    cut.Suppressed = True
    sib.Suppressed = True
    doc.recompute()
    check("both suppressed A", vol(A), 1000)
    check("both suppressed B", vol(B), 1000)
    cut.Suppressed = False
    sib.Suppressed = False
    doc.recompute()
    check("unsuppressed A", vol(A), 910)
    check("unsuppressed B", vol(B), 910)


def c6_split_part():
    """(c) a cut that splits its home part in two, and the follower's part too."""
    doc = newdoc("c6")
    S, (A, B, C) = studio3(doc)
    sk = sketch(A, "SplitSk", xyPlane(A), (4, -1, 6, 11), (24, -1, 26, 11), z=10)
    cut = A.newObject("PartDesign::Pocket", "Split")
    cut.Profile = sk
    cut.Type = "ThroughAll"
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    check("A solids", solids(A), 2)
    check("B solids", solids(B), 2)
    check("A volume", vol(A), 800)
    check("B volume", vol(B), 800)
    log("  ", status(cut), "|", status(sib))


def c7_boolean_between_parts():
    """(c) a Boolean subtracting tool T from A and from C: leader in A, follower in C, one tool."""
    doc = newdoc("c7")
    S, (A, B, C) = studio3(doc)
    T = doc.addObject("PartDesign::Body", "T")
    S.addObject(T)
    tsk = sketch(T, "TSk", xyPlane(T), (8, 4, 42, 6), z=8)
    pad(T, "TPad", tsk, 4)  # z 8..12 over x 8..42: removes 2*2*2=8 from A and from C, 10*2*2=40 from B
    doc.recompute()
    lead = A.newObject("PartDesign::Boolean", "Sub")
    lead.setObjects([T])
    lead.Type = "Cut"
    doc.recompute()
    log("  leader:", status(lead))
    fol = C.newObject("PartDesign::Boolean", "SubC")
    try:
        fol.setObjects([T])
        fol.Type = "Cut"
        fol.addProperty("App::PropertyLinkHidden", "LeadBy", "Probe")
        fol.LeadBy = lead
        doc.recompute()
        log("  follower:", status(fol))
    except Exception as e:
        log("  follower refused:", e)
    check("A minus T", vol(A), 992)
    check("C minus T", vol(C), 992)
    check("B untouched", vol(B), 1000)
    log("  T visible", T.Visibility, "consumerOf(T)",
        getattr(PartDesign, "consumerOf", lambda x: "?")(T) if hasattr(PartDesign, "consumerOf") else "?")


def c8_pattern_two_parts():
    """(c) a pattern whose original acts in A and B: leader pattern in A, follower in B bound to it."""
    doc = newdoc("c8")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Slot", (5, 2, 25, 4))  # y 2..4: 5*2*3 = 30 per part
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    lp = A.newObject("PartDesign::LinearPattern", "LPat")
    lp.Originals = [cut]
    lp.Direction = (A.Origin.OriginFeatures[1], [""])
    lp.Length = 6
    lp.Occurrences = 2
    A.Tip = lp
    doc.recompute()
    fp = B.newObject("PartDesign::LinearPattern", "LPatB")
    fp.Originals = [sib]
    fp.Direction = (B.Origin.OriginFeatures[1], [""])
    fp.addProperty("App::PropertyLinkHidden", "LeadBy", "Probe")
    fp.LeadBy = lp
    fp.setExpression("Length", "LPat.Length")
    fp.setExpression("Occurrences", "LPat.Occurrences")
    B.Tip = fp
    doc.recompute()
    log("  ", status(lp), "|", status(fp))
    check("A two slots", vol(A), 940)
    check("B two slots", vol(B), 940)
    lp.Occurrences = 3
    doc.recompute()
    check("A three slots", vol(A), 910)
    check("B follows to three", vol(B), 910)
    cut.Length = 5  # edit the original's leader
    doc.recompute()
    check("A deeper", vol(A), 1000 - 3 * 50)
    check("B deeper", vol(B), 1000 - 3 * 50)


def c9_save_reopen():
    """(c) save, close, reopen, recompute: the follower's link and bindings survive."""
    doc = newdoc("c9")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    path = os.path.join(FILES, "c9.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    A, B = doc.getObject("A"), doc.getObject("B")
    cut = doc.getObject("Cut")
    sibs = PartDesign.siblingsOf(cut)
    check("reopen: follower known", len(sibs), 1)
    check("reopen A", vol(A), 910)
    check("reopen B", vol(B), 910)
    cut.Length = 5
    doc.recompute()
    check("reopen edit: B follows", vol(B), 850)
    for o in doc.Objects:
        o.touch()
    doc.recompute()
    check("full recompute B", vol(B), 850)


# ------------------------------------------------------------------------------------------- (b)
def b1_studio_feature_outside_bodies():
    """(b) a Pocket in the studio outside every Body, Profile on A's sketch, steps in A and B."""
    doc = newdoc("b1")
    S, (A, B, C) = studio3(doc)
    sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 25, 8), z=10)
    doc.recompute()
    sf = doc.addObject("PartDesign::Pocket", "SF")
    S.addObject(sf)
    try:
        sf.Profile = sk
    except Exception as e:
        log("  Profile refused:", e)
    sf.Type = "Length"
    sf.Length = 3
    n = doc.recompute()
    log("  studio feature:", status(sf), "| in S:", sf in S.Group, "| body:", sf.getParentGeoFeatureGroup().Name if sf.getParentGeoFeatureGroup() else None)
    steps = []
    for b in (A, B):
        st = b.newObject("PartDesign::Pocket", "Step" + b.Name)
        st.Profile = sk
        st.Type = "Length"
        st.setExpression("Length", "SF.Length")
        st.addProperty("App::PropertyLinkHidden", "LeadBy", "Probe")
        st.LeadBy = sf
        steps.append(st)
    n = doc.recompute()
    log("  recomputed", n)
    for st in steps:
        log("  step:", status(st))
    check("A", vol(A), 910)
    check("B", vol(B), 910)
    seq = [o.Name for o in PartDesign.studioSequence(S)]
    log("  studioSequence", seq)
    check("studio feature in the history", "SF" in seq, True)
    sf.Length = 5
    doc.recompute()
    check("A follows edit", vol(A), 850)
    check("B follows edit", vol(B), 850)
    log("  after edit:", status(sf))
    # undo/redo of the edit
    doc.openTransaction("e")
    sf.Length = 4
    doc.commitTransaction()
    doc.recompute()
    doc.undo()
    doc.recompute()
    check("undo A", vol(A), 850)
    path = os.path.join(FILES, "b1.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    doc.recompute()
    log("  reopened:", status(doc.getObject("SF")))
    check("reopen A", vol(doc.getObject("A")), 850)
    check("reopen B", vol(doc.getObject("B")), 850)
    # Delete of the sketch's part (its Body): the studio feature's Profile
    A = doc.getObject("A")
    names = [o.Name for o in A.Group]
    doc.removeObject(A.Name)
    for nm in names:
        if doc.getObject(nm):
            doc.removeObject(nm)
    doc.recompute()
    log("  sketch's Body removed:", status(doc.getObject("SF")), "|", status(doc.getObject("StepB")))
    log("  B", vol(doc.getObject("B")))


def b2_scope_rule():
    """(b) link scope: the studio feature's Local Profile into a Body, read by isLinkValid."""
    doc = newdoc("b2")
    S, (A, B) = studio3(doc, with_c=False)
    sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 25, 8), z=10)
    sf = doc.addObject("PartDesign::Pocket", "SF")
    S.addObject(sf)
    sf.Profile = sk
    doc.recompute()
    log("  SF status:", status(sf))
    log("  SF InList", [o.Name for o in sf.InList], "OutList", [o.Name for o in sf.OutList])


def b3_noncomputing_owner():
    """(b) emulated: a non-computing owner in the studio (App::FeaturePython, re-declared Length), steps in A and B."""
    doc = newdoc("b3")
    S, (A, B, C) = studio3(doc)
    sk = sketch(A, "CutSk", xyPlane(A), (5, 2, 25, 8), z=10)
    sf = doc.addObject("App::FeaturePython", "SF")
    sf.addProperty("App::PropertyLength", "Length", "Probe").Length = 3
    S.addObject(sf)
    steps = {}
    for b in (A, B):
        st = b.newObject("PartDesign::Pocket", "Step" + b.Name)
        st.Profile = sk
        st.Type = "Length"
        st.setExpression("Length", "SF.Length")
        st.addProperty("App::PropertyLinkHidden", "LeadBy", "Probe")
        st.LeadBy = sf
        steps[b.Name] = st
    doc.recompute()
    log("  owner:", status(sf), "| steps:", status(steps["A"]), "|", status(steps["B"]))
    check("A", vol(A), 910)
    check("B", vol(B), 910)
    seq = [o.Name for o in PartDesign.studioSequence(S)]
    check("owner is a history row", "SF" in seq, False)
    log("  sequence", seq)
    # report 21: B only = A's step suppressed (no leader to pass through)
    steps["A"].Suppressed = True
    doc.recompute()
    check("B only: A", vol(A), 1000)
    check("B only: B", vol(B), 910)
    steps["A"].Suppressed = False
    doc.openTransaction("e")
    sf.Length = 5
    doc.commitTransaction()
    doc.recompute()
    check("edit A", vol(A), 850)
    check("edit B", vol(B), 850)
    doc.undo()
    doc.recompute()
    check("undo B", vol(B), 910)
    doc.redo()
    doc.recompute()
    check("redo B", vol(B), 850)
    # reorder: B's Fill after the cut, then the cut's B step below it (the same fan-out as (c))
    fsk = sketch(B, "FillSk", xyPlane(B), (20, 2, 25, 8), z=5)
    fill = pad(B, "Fill", fsk, 5)
    doc.recompute()
    check("B cut then fill", vol(B), 1000)
    try:
        PartDesign.moveInStudio(S, [steps["B"]], fill)
        doc.recompute()
        check("B after the step's drag", vol(B), 850)
        log("  sequence", [o.Name for o in PartDesign.studioSequence(S)])
    except Exception as e:
        log("  drag refused:", e)
    # Delete part on the sketch's part
    dp = PartDesign.deletePart(A)
    doc.recompute()
    check("A deleted", vol(A) or 0.0, 0.0)
    check("B keeps its cut", vol(B), 850)
    path = os.path.join(FILES, "b3.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    doc.getObject("SF").Length = 4
    doc.recompute()
    check("reopen edit B", vol(doc.getObject("B")), 880)
    log("  reopened owner:", status(doc.getObject("SF")))


def c10_scope_added_late():
    """(c) a part added to an early feature's scope when that part has later features (mid-chain insert)."""
    doc = newdoc("c10")
    S, (A, B, C) = studio3(doc)
    sk, cut = cutIn(A, "Cut", (5, 2, 25, 8))
    doc.recompute()
    fsk = sketch(B, "FillSk", xyPlane(B), (20, 2, 25, 8), z=8)
    fill = pad(B, "Boss", fsk, 4)  # z 8..12 over x 20..25 y 2..8: +60 on B, made after the cut
    doc.recompute()
    check("B with boss", vol(B), 1060)
    seq0 = [o.Name for o in PartDesign.studioSequence(S)]
    [sib] = PartDesign.makeSiblings(cut, [B])
    doc.recompute()
    log("  B group", [o.Name for o in B.Group], "sequence", [o.Name for o in PartDesign.studioSequence(S)])
    # Onshape: the cut is at its history point, before Boss, which refills z 8..10: B = 1030.
    # Appended after Boss, the cut also removes Boss's z 8..10: B = 970
    check("B: follower at the leader's history point", vol(B), 1030)


CASES = os.environ.get("BAKEOFF_CASES")
ALL = (c1_two_parts_and_other_only, c2_edit_undo_redo, c3_delete_leader_only, c4_reorder_rollback,
           c5_suppress, c6_split_part, c7_boolean_between_parts, c8_pattern_two_parts, c9_save_reopen,
           b1_studio_feature_outside_bodies, b2_scope_rule, b3_noncomputing_owner, c10_scope_added_late)
for fn in [f for f in ALL if not CASES or f.__name__.split("_")[0] in CASES.split(",")]:
    case(fn)

log("")
log("FAILS: %d" % len(fails))
for f in fails:
    log("  " + f)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
os._exit(0)
