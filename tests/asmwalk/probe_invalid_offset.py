# Probe (asm-walk finding 2): a Fastened mate made invalid (its face gone), then its offset edited.
# Expected (B3, Onshape): the mate is in error, the solve leaves it out, nothing moves.
import FreeCAD as App
import Part
import JointObject
V = App.Vector

d = App.newDocument("P2")
a = d.addObject("PartDesign::Body", "A")
box = a.newObject("PartDesign::AdditiveBox", "ABox"); box.Length, box.Width, box.Height = 20, 20, 10
b = d.addObject("PartDesign::Body", "B")
pad = b.newObject("PartDesign::AdditiveCylinder", "Cyl"); pad.Radius, pad.Height = 5, 20
d.recompute()
asm = d.addObject("Assembly::AssemblyObject", "Assembly"); asm.Type = "Assembly"
jg = asm.newObject("Assembly::JointGroup", "Joints")
la = asm.newObject("App::Link", "LA"); la.LinkedObject = a
lb = asm.newObject("App::Link", "LB"); lb.LinkedObject = b; lb.Placement = App.Placement(V(60, 0, 0), App.Rotation())
d.recompute()
g = jg.newObject("App::FeaturePython", "G"); JointObject.GroundedJoint(g, la)
def top(shape):
    z = shape.BoundBox.ZMax
    return [f"Face{i}" for i, f in enumerate(shape.Faces, 1) if abs(f.CenterOfMass.z - z) < 1e-6 and f.normalAt(0, 0).z > 0.5][0]
tb, ta = top(b.Shape), top(a.Shape)
j = jg.newObject("App::FeaturePython", "F"); JointObject.Joint(j, 0)
j.Proxy.setJointConnectors(j, [[lb, [tb, tb]], [la, [ta, ta]]])
d.recompute(); asm.solve(); d.recompute()
print("valid mate: B at", lb.Placement.Base, "valid", j.isValid())
# the circle redrawn: B's top face gets a new name, the mate loses its face
b.removeObject(pad); d.removeObject(pad.Name)
pad2 = b.newObject("PartDesign::AdditivePrism", "Hex"); pad2.Polygon = 6; pad2.Circumradius, pad2.Height = 5, 20
d.recompute(); asm.solve(); d.recompute()
p0 = App.Placement(lb.Placement)
print("face gone: B at", p0.Base, "valid", j.isValid(), j.getStatusString()[:90])
for off in (3.0, 0.0, -2.0):
    j.Offset2 = App.Placement(V(0, 0, off), App.Rotation())
    d.recompute()
    print(f"offset {off}: B at", lb.Placement.Base, "valid", j.isValid())
    rc = asm.solve(); d.recompute()
    print(f"   after solve rc={rc}: B at", lb.Placement.Base)
print("MOVED" if not lb.Placement.isSame(p0, 1e-6) else "STAYED")
