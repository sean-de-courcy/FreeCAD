# repro_unpark.py: a studio-list move that puts a Pocket above its sketch parks the Pocket's Profile (red, Profile cleared);
# an unrelated move afterwards gives the Profile back while the sketch still comes after the Pocket, and the Pocket builds
# green from a later sketch (ops#640, mac scout 4, D+ seed 34 reduced to these two steps). Designed geometry: the D+ studio
# (fuzzplus.py) at its defaults, owner mode.
# Run: FreeCADCmd repro_unpark.py   (prints one PROBE line per step)
import os
os.environ["FUZZ_NOMAIN"] = "1"
os.environ.setdefault("FUZZ_TAG", "repro_unpark")
HERE = os.path.dirname(os.path.abspath(os.environ.get("RP_SELF", __file__)))
g = {"__name__": "fuzzplus"}
exec(open(os.path.join(HERE, "fuzzplus.py")).read(), g)
App, PartDesign = g["App"], g["PartDesign"]
doc = App.newDocument("P")
g["Studio"](doc).build()
PartDesign.studioList(doc, True)
doc.recompute()


def show(tag):
    names = [e.Name for e in PartDesign.studioList(doc).Entries]
    pos = lambda n: names.index(n) if n in names else None
    s = doc.getObject("Slot")
    prof = getattr(s.Profile[0], "Name", s.Profile[0]) if s.Profile else None
    print("PROBE %-24s Slot@%s SlotSk@%s Slot %s Profile=%s part volume %.4f" % (
        tag, pos("Slot"), pos("SlotSk"), s.State, prof, doc.getObject("Plate").Shape.Volume))


show("built")
PartDesign.studioMove(doc.getObject("Slot"), 23); doc.recompute(); show("move Slot 24 -> 23")
PartDesign.studioMove(doc.getObject("MirBoss"), 13); doc.recompute(); show("move MirBoss 12 -> 13")
for o in doc.Objects:
    o.touch()
doc.recompute(); show("touch all, recompute")
