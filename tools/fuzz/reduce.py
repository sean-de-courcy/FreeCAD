# reduce.py: replay recorded fuzz steps on a fresh studio and minimise the prefix that makes RED_TARGET Invalid
# (or breaks the invariant). Env: RED_LOG (jsonl), RED_LAST (step number of the failing step), RED_TARGET (object name).
import os, json, re
os.environ.setdefault("FUZZ_TAG", "reduce")
src = open(os.path.join(os.environ.get("FUZZ_DIR") or os.path.dirname(os.path.abspath(__file__)), "fuzz.py")).read()
exec(src.split("def main():")[0])

rows = [json.loads(l) for l in open(os.environ["RED_LOG"])]
last = int(os.environ["RED_LAST"]); target = os.environ["RED_TARGET"]
steps = [r for r in rows if isinstance(r.get("step"), int) and 0 < r["step"] <= last and r.get("what")]
steps = [r for r in steps if "refused" not in r["what"] and (not r.get("red") or r["step"] == last)]   # reverted steps left out


def apply(doc, what):
    m = re.match(r"move (\w+) \d+ -> (\d+)", what)
    if m:
        e = doc.getObject(m.group(1))
        try:
            PartDesign.studioMove(e, int(m.group(2)))
        except ValueError:
            pass
        return
    m = re.match(r"(\w+)\.(\w+) = (\S+)", what)
    obj, key, v = doc.getObject(m.group(1)), m.group(2), float(m.group(3))
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        obj.setDatum(datumKey(obj, key), App.Units.Quantity("%s mm" % v))
    else:
        cur = getattr(obj, key)
        setattr(obj, key, int(v) if isinstance(cur, int) else v)


n = [0]
def fails(seq):
    n[0] += 1
    doc = App.newDocument("Red%d" % n[0])
    try:
        Studio(doc).build()
        if os.environ.get("RED_MODE") == "revert":   # the last step, then its exact undo, must restore the state
            for r in seq[:-1]:
                apply(doc, r["what"]); doc.recompute()
            w = seq[-1]["what"]
            m = re.match(r"move (\w+) (\d+) -> (\d+)", w)
            before = signature(doc)
            if m:
                e = doc.getObject(m.group(1))
                PartDesign.studioMove(e, int(m.group(3))); doc.recompute()
                PartDesign.studioMove(e, int(m.group(2))); doc.recompute()
            else:
                m = re.match(r"(\w+)\.(\w+) = (\S+)", w); obj = doc.getObject(m.group(1)); key = m.group(2)
                if obj.isDerivedFrom("Sketcher::SketchObject"):
                    i = datumKey(obj, key); old = obj.Constraints[i].Value
                    apply(doc, w); doc.recompute(); obj.setDatum(i, App.Units.Quantity("%s mm" % old)); doc.recompute()
                else:
                    old = getattr(obj, key); apply(doc, w); doc.recompute(); setattr(obj, key, old); doc.recompute()
            return bool(compare(signature(doc), before))
        for r in seq:
            apply(doc, r["what"]); doc.recompute()
        o = doc.getObject(target)
        return "Invalid" in o.State
    finally:
        App.closeDocument(doc.Name)


cur = steps
assert fails(cur), "full prefix does not reproduce"
# ddmin over all but the last step
changed = True
while changed:
    changed = False
    for i in range(len(cur) - 1):
        trial = cur[:i] + cur[i + 1:]
        if fails(trial):
            cur = trial; changed = True; break
print("REDUCED", json.dumps([r["what"] for r in cur]))
