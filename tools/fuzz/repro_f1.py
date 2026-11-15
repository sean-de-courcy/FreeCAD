# repro_f1.py (block F, fuzz seed 1 reduced): a red pattern upstream makes a later dimension edit break a dress-up's picks.
# Designed geometry: plate 40 x 40 x 10; rib 20 x 3 padded 4 on top; linear pattern of the rib along Y (8 mm, 2);
# tab 6 x 16 padded 5 on top; chamfer 0.6 on the tab's 4 top edges.
# Expected (Onshape): the chamfer keeps its 4 edges through every step (the tab's own edges never change identity).
import FreeCAD as App, Part, Sketcher, PartDesign
V = App.Vector


def rect(sk, x, y, w, h):
    p = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
    f = len(sk.Geometry)
    for i in range(4):
        sk.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", f + i, 2, f + (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", f)); sk.addConstraint(Sketcher.Constraint("Horizontal", f + 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", f + 1)); sk.addConstraint(Sketcher.Constraint("Vertical", f + 3))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, f, 1, x)); sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, f, 1, y))
    sk.addConstraint(Sketcher.Constraint("DistanceX", f, 1, f, 2, w)); sk.addConstraint(Sketcher.Constraint("DistanceY", f + 1, 1, f + 1, 2, h))


doc = App.newDocument("ReproF1"); PartDesign.studioList(doc, True)
b = doc.addObject("PartDesign::Body", "B"); o = b.Origin.OriginFeatures


def sketch(name, z, *r):
    s = b.newObject("Sketcher::SketchObject", name); s.AttachmentSupport = [(o[3], "")]; s.MapMode = "FlatFace"
    s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation()); rect(s, *r); PartDesign.studioInsert(s, -1); return s


def pad(name, prof, length):
    p = b.newObject("PartDesign::Pad", name); p.Profile = prof; p.Length = length
    PartDesign.studioInsert(p, -1); doc.recompute(); return p


pad("Plate", sketch("PlateSk", 0, -20, -20, 40, 40), 10)
rib = pad("Rib", sketch("RibSk", 10, -5, -15, 20, 3), 4)
pat = doc.addObject("PartDesign::LinearPattern", "RibPat")
pat.Originals = [rib]; pat.Direction = (o[1], [""]); pat.Length = 8; pat.Occurrences = 2
b.addObject(pat); PartDesign.studioInsert(pat, -1); doc.recompute()
tab = pad("Tab", sketch("TabSk", 10, -18, -8, 6, 16), 5)
top = ["Edge%d" % i for i, e in enumerate(tab.Shape.Edges, 1) if all(abs(v.Point.z - 15) < 1e-6 and v.Point.x < -11 for v in e.Vertexes)]
ch = b.newObject("PartDesign::Chamfer", "Chamfer"); ch.Base = (tab, top); ch.Size = 0.6
PartDesign.studioInsert(ch, -1); doc.recompute()


def report(step):
    print("F1 %-34s pattern %-7s chamfer %-11s %s" % (step, "valid" if pat.isValid() else "RED", ch.State[0], ch.getStatusString()[:110]))


report("built")
tab.Length = 9; doc.recompute(); report("tab 5 -> 9 (pattern valid)")
tab.Length = 5; doc.recompute()
pat.Length = 60; doc.recompute(); report("pattern 8 -> 60 (copy off the plate)")
tab.Length = 9; doc.recompute(); report("tab 5 -> 9 (pattern red)")
pat.Length = 8; doc.recompute(); report("pattern 60 -> 8")
