# Probe: the sign of a Fastened mate's offset with and without a grounded part at mate time.
import FreeCAD as App
import JointObject
V = App.Vector

def run(ground_first):
    d = App.newDocument("P")
    a = d.addObject("Part::Box", "A"); a.Length, a.Width, a.Height = 40, 20, 10
    b = d.addObject("Part::Box", "B"); b.Length, b.Width, b.Height = 20, 10, 5
    d.recompute()
    asm = d.addObject("Assembly::AssemblyObject", "Assembly"); asm.Type = "Assembly"
    jg = asm.newObject("Assembly::JointGroup", "Joints")
    la = asm.newObject("App::Link", "LA"); la.LinkedObject = a
    lb = asm.newObject("App::Link", "LB"); lb.LinkedObject = b
    lb.Placement = App.Placement(V(60, 0, 0), App.Rotation())
    d.recompute()
    if ground_first:
        g = jg.newObject("App::FeaturePython", "G"); JointObject.GroundedJoint(g, la)
    j = jg.newObject("App::FeaturePython", "F"); JointObject.Joint(j, 0)
    # moving first (B), as the dialog's picks
    j.Proxy.setJointConnectors(j, [[lb, ["Face6", "Face6"]], [la, ["Face6", "Face6"]]])
    j.Offset2 = App.Placement(V(0, 0, 3), App.Rotation())
    if not ground_first:
        g = jg.newObject("App::FeaturePython", "G"); JointObject.GroundedJoint(g, la)
    d.recompute(); asm.solve(); d.recompute()
    r1 = j.Reference1[0].Name if hasattr(j.Reference1[0], "Name") else j.Reference1
    print("ground_first", ground_first, "Ref1 owner", j.Reference1, "B top centre", lb.Placement.multVec(V(10, 5, 5)), "A top centre (20,10,10)")
    App.closeDocument(d.Name)

run(True)
run(False)
