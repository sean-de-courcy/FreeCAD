# repro_f2.py (block F, fuzz seed 13 reduced): a plate-thickness edit re-finds a chamfer pick by geometry; moving a feature
# down one and straight back then loses that pick, and the part changes for good.
# Designed geometry: plate 60 x 40 x 10; a rib 25 x 3 padded 4 on top, running into the boss's corner (x -10..15, y -12..-9);
# a boss 10 x 10 padded 6 on top (x 14..24, y -12..-2); a draft of 3 deg on the boss's side faces (neutral plane: its top);
# a chamfer of 0.8 on the boss's 4 top edges.
# Expected (Onshape): the chamfer keeps its 4 edges, and moving the boss down and back restores the part exactly.
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


doc = App.newDocument("ReproF2"); PartDesign.studioList(doc, True)
b = doc.addObject("PartDesign::Body", "B"); o = b.Origin.OriginFeatures


def sketch(name, z, *r):
    s = b.newObject("Sketcher::SketchObject", name); s.AttachmentSupport = [(o[3], "")]; s.MapMode = "FlatFace"
    s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation()); rect(s, *r); PartDesign.studioInsert(s, -1); return s


def feat(kind, name, **kw):
    f = b.newObject("PartDesign::" + kind, name)
    for k, v in kw.items():
        setattr(f, k, v)
    PartDesign.studioInsert(f, -1); doc.recompute(); return f


plate = feat("Pad", "Plate", Profile=sketch("PlateSk", 0, -30, -20, 60, 40), Length=10)
feat("Pad", "Rib", Profile=sketch("RibSk", 10, -10, -12, 25, 3), Length=4)
boss = feat("Pad", "Boss", Profile=sketch("BossSk", 10, 14, -12, 10, 10), Length=6)
sh = boss.Shape
sides = ["Face%d" % i for i, f in enumerate(sh.Faces, 1)
         if abs(f.normalAt(0, 0).z) < 1e-6 and 13 < f.CenterOfMass.x < 25 and -13 < f.CenterOfMass.y < -1 and f.CenterOfMass.z > 10]
top = ["Face%d" % i for i, f in enumerate(sh.Faces, 1) if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 16) < 1e-6]
feat("Draft", "Draft", Base=(boss, sides), NeutralPlane=(boss, top[:1]), Angle=3)
last = b.Tip
edges = ["Edge%d" % i for i, e in enumerate(last.Shape.Edges, 1) if all(abs(v.Point.z - 16) < 1e-6 and v.Point.x > 13 for v in e.Vertexes)]
ch = feat("Chamfer", "Chamfer", Base=(last, edges), Size=0.8)


def report(step):
    print("F2 %-24s chamfer %-11s volume %.4f  %s" % (step, ch.State[-1], b.Shape.Volume, ch.getStatusString()[:150]))


report("built")
plate.Length = 11.69; doc.recompute(); report("plate 10 -> 11.69"); v0 = b.Shape.Volume
i = [e.Name for e in PartDesign.studioList(doc).Entries].index("Boss")
PartDesign.studioMove(boss, i + 1); doc.recompute(); report("boss moved down one")
PartDesign.studioMove(boss, i); doc.recompute(); report("boss moved back")
print("F2 restored:", abs(b.Shape.Volume - v0) < 1e-6, "(volume change %.4f)" % (b.Shape.Volume - v0))
