# undoreplay.py: replay D+ edits, each in its own transaction, then undo the last UR_UNDO of them (default: all) and
# compare the state with the signature recorded after the target edit; then redo and compare with the top (ops#640).
# Triage of D+ undo_fail: a diff here with no fuzz bookkeeping in the way is FreeCAD's, not the harness's.
# Run: UR_STEPS="BossSk.Cx = -35.72;topo LateSk plain -> split" [UR_UNDO=<n>] [FUZZ_OWNER=0|1] FreeCADCmd undoreplay.py
#   UR_FULL=1 also compares the undone state with a full recompute of itself (touch all, recompute).
import os, json
os.environ["FUZZ_NOMAIN"] = "1"
os.environ.setdefault("FUZZ_TAG", "undoreplay")
HERE = os.path.dirname(os.path.abspath(os.environ.get("UR_SELF", __file__)))
exec(open(os.path.join(HERE, "fuzzplus.py")).read())
_src = open(os.path.join(HERE, "reduceplus.py")).read()
exec(_src[_src.index("def play(doc, what):"):_src.index("def trial(")])

steps = [x.strip() for x in os.environ["UR_STEPS"].split(";") if x.strip()]
nundo = int(os.environ.get("UR_UNDO", str(len(steps))))
doc = App.newDocument("UR")
doc.UndoMode = 1
st = Studio(doc).build()
PartDesign.studioList(doc, True)
doc.recompute()
sigs = [signature(doc)]
for i, w in enumerate(steps, 1):
    doc.openTransaction("ur%d" % i)
    play(doc, w)
    doc.recompute()
    doc.commitTransaction()
    sigs.append(signature(doc))
    print("UR step %d %s vol %.6f errors %s" % (i, w, sigs[-1].get("vol") or 0, sigs[-1]["errors"]))
print("UR undo stack", list(doc.UndoNames))
for _ in range(nundo):
    doc.undo()
doc.recompute()
su = signature(doc)
du = compare(su, sigs[len(steps) - nundo])
print("UR undo %d -> state %d: %s" % (nundo, len(steps) - nundo, "OK" if not du else json.dumps(du)[:1500]))
if os.environ.get("UR_FULL") == "1":
    for o in doc.Objects:
        o.touch()
    doc.recompute()
    print("UR undone + full recompute vs target: %s" % (lambda d: "OK" if not d else json.dumps(d)[:800])(compare(signature(doc), sigs[len(steps) - nundo])))
else:
    for _ in range(nundo):
        doc.redo()
    doc.recompute()
    dr = compare(signature(doc), sigs[-1])
    print("UR redo %d -> top: %s" % (nundo, "OK" if not dr else json.dumps(dr)[:800]))
if os.environ.get("UR_SAVE"):
    doc.saveAs(os.environ["UR_SAVE"])
