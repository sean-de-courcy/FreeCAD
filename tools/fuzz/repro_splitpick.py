# repro_splitpick.py: a studio Chamfer (StudioPickIds, as the GUI's makeStudioDressUp makes it) loses its picks when a
# sketch edge upstream is split with the Sketcher's split, while the same chamfer as a Body member keeps them (ops#640,
# scout 3). Designed geometry: the D+ studio (fuzzplus.py) at its defaults; one GUI-style split, nothing else.
# Run: FreeCADCmd repro_splitpick.py   (prints one REPRO line per sketch and dress-up kind)
import os
os.environ["FUZZ_NOMAIN"] = "1"
os.environ.setdefault("FUZZ_TAG", "repro_splitpick")
HERE = os.path.dirname(os.path.abspath(os.environ.get("RP_SELF", __file__)))
src = open(os.path.join(HERE, "fuzzplus.py")).read()
for sketch, dress in (("BaseSk", "Pk1Chamfer"), ("Boss2Sk", "Boss2Chamfer")):
    for owner in (True, False):
        g = {"__name__": "fuzzplus"}
        exec(src, g)
        g["OWNER_DRESS"] = owner
        doc = g["App"].newDocument("R")
        g["Studio"](doc).build()
        g["PartDesign"].studioList(doc, True)
        doc.recompute()
        v0 = doc.getObject("Plate").Shape.Volume
        g["topoEdit"](doc.getObject(sketch), "split")
        doc.recompute()
        o = doc.getObject(dress)
        bad = "Invalid" in o.State or "Error" in o.State
        print("REPRO split %s: %s as %s: %s (%s); part volume %.4f -> %.4f" % (
            sketch, dress, "studio owner" if owner else "Body member", "RED" if bad else "ok",
            o.getStatusString()[:200], v0, doc.getObject("Plate").Shape.Volume))
        g["App"].closeDocument(doc.Name)
