# repro_d1.py: fuzz D+ finding 1 (ops#640). The designed fuzz studio; suppress MirSlot, then Base.Length = 10.87:
# Pk1Chamfer turns red ("Missing edge reference: EdgeN (candidates: EdgeN)") although a fresh build at the same values
# is green. REPRO_COPY=1 opens (and closes) a saved copy of the document between the two edits: then it stays green.
# REPRO_NOSUP=1 leaves out the suppress. Run: FreeCADCmd tools/fuzz/repro_d1.py (FUZZ_OUT=<dir> for the scratch files).
import os, shutil
os.environ["FUZZ_NOMAIN"] = "1"
here = os.path.dirname(os.path.abspath(os.environ.get("REPRO_SELF", __file__)))
exec(open(os.path.join(here, "fuzzplus.py")).read())
doc = App.newDocument("D1"); doc.UndoMode = 1
st = Studio(doc).build(); PartDesign.studioList(doc, True); doc.recompute()
print("start red:", signature(doc)["errors"])
if os.environ.get("REPRO_NOSUP") != "1":
    transact(doc, lambda d: PartDesign.studioSuppress(d.getObject("MirSlot"), True))
print("after suppress red:", signature(doc)["errors"])
if os.environ.get("REPRO_COPY") == "1":
    doc.saveAs("%s/d1.FCStd" % OUT); shutil.copyfile("%s/d1.FCStd" % OUT, "%s/d1-copy.FCStd" % OUT)
    App.closeDocument(App.openDocument("%s/d1-copy.FCStd" % OUT).Name)
transact(doc, lambda d: setattr(d.getObject("Base"), "Length", 10.87))
live = signature(doc)
rec, _s = freshCheck(doc, live, st.params, 0)
print("after Base.Length red:", live["errors"], "| fresh check:", rec.get("fresh"), rec.get("fresh_diff", {}).get("red"))
print("RESULT", "BUG" if "Pk1Chamfer" in live["errors"] else "ok")
