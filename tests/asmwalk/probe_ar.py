# Probes against oracle 26's AR1 and AR2 (notes/onshape-facts.md, "Assembly robustness, batch R1 part 1").
# Blk 20x20x10 grounded, Pin d10 h20 bottom-face centre fastened on Blk's top-face centre (flipped onto it),
# linear pattern of 10 at 25 along a Blk X edge.
import FreeCAD as App
import Part
import AssemblyPattern
import JointObject
V = App.Vector


def build(name, top_edge):
    d = App.newDocument(name)
    blk = d.addObject("PartDesign::Body", "Blk")
    box = blk.newObject("PartDesign::AdditiveBox", "BlkBox"); box.Length = box.Width = 20; box.Height = 10
    pin = d.addObject("PartDesign::Body", "Pin")
    cyl = pin.newObject("PartDesign::AdditiveCylinder", "Cyl"); cyl.Radius, cyl.Height = 5, 20
    d.recompute()
    asm = d.addObject("Assembly::AssemblyObject", "Assembly"); asm.Type = "Assembly"
    jg = asm.newObject("Assembly::JointGroup", "Joints")
    lb = asm.newObject("App::Link", "BlkI"); lb.LinkedObject = blk
    lp = asm.newObject("App::Link", "PinI"); lp.LinkedObject = pin; lp.Placement = App.Placement(V(60, 0, 0), App.Rotation())
    d.recompute()
    g = jg.newObject("App::FeaturePython", "G"); JointObject.GroundedJoint(g, lb)
    face = lambda s, z, up: [f"Face{i}" for i, f in enumerate(s.Faces, 1) if f.Surface.TypeId == "Part::GeomPlane"
                             and abs(f.CenterOfMass.z - z) < 1e-6 and (f.normalAt(0, 0).z > 0.5) == up][0]
    tb, bp = face(blk.Shape, 10, True), face(pin.Shape, 0, False)
    j = jg.newObject("App::FeaturePython", "F"); JointObject.Joint(j, 0)
    j.Proxy.setJointConnectors(j, [[lp, [bp, bp]], [lb, [tb, tb]]])
    d.recompute(); asm.solve(); d.recompute()
    z = 10 if top_edge else 0
    edge = [f"Edge{i}" for i, e in enumerate(blk.Shape.Edges, 1)
            if all(abs(v.Point.z - z) < 1e-7 and abs(v.Point.y) < 1e-7 for v in e.Vertexes)][0]
    pat = AssemblyPattern.makePattern(asm, "Linear", [lp], (lb, [edge]))
    pat.Count, pat.Distance = 10, 25
    d.recompute(); asm.solve(); d.recompute()
    return d, blk, box, asm, lp, j, pat


def where(lp, pat):
    pts = [lp.Placement.multVec(V(0, 0, 0))] + [c.Placement.multVec(V(0, 0, 0)) for c in sorted(pat.Instances, key=lambda c: c.PatternIndex)]
    return [(round(p.x, 3), round(p.y, 3), round(p.z, 3)) for p in pts]


# AR1: a fillet r2 on Blk's 4 top edges; the pattern's direction is a top edge
d, blk, box, asm, lp, j, pat = build("AR1", True)
print("AR1 before:", where(lp, pat)[:3], "flipped pin bottom at", lp.Placement.multVec(V(0, 0, 0)))
before = where(lp, pat)
H = 10
edges = [f"Edge{i}" for i, e in enumerate(box.Shape.Edges, 1) if all(abs(v.Point.z - H) < 1e-7 for v in e.Vertexes)]
fil = blk.newObject("PartDesign::Fillet", "Fil"); fil.Base = (box, edges); fil.Radius = 2
d.recompute(); rc = asm.solve(); d.recompute()
after = where(lp, pat)
print("AR1 after: mate valid", j.isValid(), "| pattern State", pat.State, "| copies", len(pat.Instances),
      "| placements kept" if after == before else f"| MOVED {after[:3]}", "| solve", rc)
print("   Onshape: mate OK, pattern ERROR 'Failed to compute pattern direction', instances keep their placements")
App.closeDocument(d.Name)

# AR2: a 10x20 pocket 3 deep over the x 10..20 half of Blk's top
d, blk, box, asm, lp, j, pat = build("AR2", False)
before = where(lp, pat)
print("AR2 pattern props before:", [(n, getattr(pat, n)) for n in pat.PropertiesList if "Dir" in n or "Ref" in n][:4])
for i, e in enumerate(blk.Shape.Edges, 1):
    if all(abs(v.Point.z) < 1e-7 and abs(v.Point.y) < 1e-7 for v in e.Vertexes):
        print("   bottom front edge before", f"Edge{i}", e.Vertexes[0].Point, "->", e.Vertexes[-1].Point)
print("   joint Placement2", j.Placement2.Base, "Reference2", j.Reference2[1])
cut = blk.newObject("PartDesign::SubtractiveBox", "Pocket"); cut.Length, cut.Width, cut.Height = 10, 20, 3
cut.Placement = App.Placement(V(10, 0, 7), App.Rotation())
d.recompute(); rc = asm.solve(); d.recompute()
after = where(lp, pat)
ref = pat.Direction if hasattr(pat, "Direction") else None
print("AR2 pattern props:", [(n, getattr(pat, n)) for n in pat.PropertiesList if "Dir" in n or "Ref" in n][:4])
for i, e in enumerate(blk.Shape.Edges, 1):
    if all(abs(v.Point.z) < 1e-7 and abs(v.Point.y) < 1e-7 for v in e.Vertexes):
        print("   bottom front edge now", f"Edge{i}", e.Vertexes[0].Point, "->", e.Vertexes[-1].Point)
print("   joint Placement2", j.Placement2.Base, "Reference2", j.Reference2[1])
print("AR2 before", before[:2], "after", after[:2], "| mate valid", j.isValid(), j.getStatusString()[:100], "| solve", rc)
print("   Onshape: mate OK, no warning; Pin re-attaches to the remaining top face's centroid: x 10 -> 6, z 10; instances shift -4 in x")
App.closeDocument(d.Name)
