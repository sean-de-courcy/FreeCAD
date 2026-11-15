# reduceplus.py: cut a fuzz D+ run's steps 1..K to a minimal list that still ends in a SILENT (or LOUD) fresh check.
# Run: RED_LOG=<run>.jsonl RED_K=<step> [RED_WANT=SILENT|LOUD] FUZZ_OUT=<dir> FreeCADCmd tools/fuzz/reduceplus.py
# Prints the minimal step list and saves the end state as <dir>/reduced.FCStd.
import os, json, re
os.environ["FUZZ_NOMAIN"] = "1"
os.environ.setdefault("FUZZ_TAG", "reduce")
exec(open(os.path.join(os.path.dirname(os.path.abspath(os.environ.get("RED_SELF", __file__))), "fuzzplus.py")).read())

WANT = os.environ.get("RED_WANT", "SILENT")
K = int(os.environ["RED_K"])
SAVE_EACH = os.environ.get("RED_SAVE", "1") == "1"
STEPS_IN = []
for line in open(os.environ["RED_LOG"]):
    r = json.loads(line)
    if isinstance(r.get("step"), int) and 1 <= r["step"] <= K and r.get("what") and not r.get("refused") and not r.get("exc"):
        if r["what"].startswith("undo:") or r["what"] == "refused":
            continue
        STEPS_IN.append((r["step"], r["what"], bool(r.get("red")) and HEAL))


def play(doc, what):
    m = re.match(r"(\w+)\.(\w+) = (\S+)$", what)
    if m:
        o = doc.getObject(m.group(1)); key = m.group(2); v = float(m.group(3))
        if o.isDerivedFrom("Sketcher::SketchObject"):
            o.setDatum(datumKey(o, key), App.Units.Quantity("%s mm" % v))
        else:
            setattr(o, key, int(v) if key == "Occurrences" else v)
        return
    m = re.match(r"move (\w+) \d+ -> (\d+)", what)
    if m:
        PartDesign.studioMove(doc.getObject(m.group(1)), int(m.group(2))); return
    m = re.match(r"topo (\w+) \w+ -> (\w+)", what)
    if m:
        sk = doc.getObject(m.group(1)); new = "" if m.group(2) == "plain" else m.group(2)
        vals = sketchVals(sk)
        if new != "extra":
            vals = {k: x for k, x in vals.items() if not k.startswith("X")}
        sk.deleteAllGeometry(); drawSketch(sk, vals, new); return
    m = re.match(r"(un)?suppress (\w+)$", what)
    if m:
        PartDesign.studioSuppress(doc.getObject(m.group(2)), m.group(1) is None); return
    m = re.match(r"delete (\w+)$", what)
    if m:
        e = doc.getObject(m.group(1)); PartDesign.studioRemove(e); doc.removeObject(m.group(1)); return
    raise ValueError("unknown step " + what)


def trial(seq, save=False):
    doc = App.newDocument("Red"); doc.UndoMode = 1
    try:
        st = Studio(doc).build(); PartDesign.studioList(doc, True); doc.recompute()
        for _k, what, healed in seq:
            m = re.match(r"undo (\d+) \+ redo", what)
            try:
                if m:
                    d = min(int(m.group(1)), doc.UndoCount)
                    for _ in range(d):
                        doc.undo()
                    doc.recompute()
                    for _ in range(d):
                        doc.redo()
                    doc.recompute()
                    continue
                transact(doc, lambda dd: play(dd, what))
            except Exception:
                continue
            if SAVE_EACH:   # the fuzz run saves the live document at every check (fullFrom); a save is state too
                doc.saveAs("%s/replay-cur.FCStd" % OUT)
            if what.startswith("delete ") or healed:
                doc.undo(); doc.recompute()
        live = signature(doc)
        rec, _s = freshCheck(doc, live, st.params, 0)
        if save:
            doc.saveAs("%s/reduced.FCStd" % OUT)
            print("END", json.dumps(rec, default=str)[:900])
        return rec.get("fresh") == WANT
    finally:
        App.closeDocument(doc.Name)


seq = list(STEPS_IN)
print("steps", len(seq), "reproduces:", trial(seq))
n = 2
while len(seq) >= 2:
    chunk = max(1, len(seq) // n); cut = False
    for i in range(0, len(seq), chunk):
        t = seq[:i] + seq[i + chunk:]
        if t and trial(t):
            seq = t; n = max(n - 1, 2); cut = True
            break
    if not cut:
        if chunk == 1:
            break
        n = min(len(seq), n * 2)
print("MINIMAL", [(k, w) for k, w, _h in seq])
trial(seq, True)
