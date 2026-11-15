# Probes against oracle 26's AR6, AR7, AR9, AR10, AR11 (notes/onshape-facts.md, R1.6-R1.11).
# Blk 20x20x10 grounded, Fillet r2 on its 4 top edges, then a pocket 3 deep over x 10..20 of the top
# (the top face is x 2..10, y 2..18). Pin: a d10 sketch padded 20, upright. Fastened: Pin's bottom
# face centre onto Blk's top face centre. Linear pattern of 6 at 25 along Blk's bottom front X edge.
# Designed geometry only; run with FreeCADCmd.
import math
import FreeCAD as App
import Part
import AssemblyPattern
import JointObject
V = App.Vector


def r3(p):
    return (round(p.x, 3), round(p.y, 3), round(p.z, 3))


class M:
    def __init__(self, name, pinFirst=True, hexagon=False, count=6):
        d = self.d = App.newDocument(name)
        self.blk = d.addObject("PartDesign::Body", "Blk")
        self.box = self.blk.newObject("PartDesign::AdditiveBox", "BlkBox")
        self.box.Length = self.box.Width = 20; self.box.Height = 10
        d.recompute()
        top = [f"Edge{i}" for i, e in enumerate(self.box.Shape.Edges, 1) if all(abs(v.Point.z - 10) < 1e-7 for v in e.Vertexes)]
        self.fil = self.blk.newObject("PartDesign::Fillet", "Fillet1"); self.fil.Base = (self.box, top); self.fil.Radius = 2
        d.recompute()
        self.pk = self.blk.newObject("PartDesign::SubtractiveBox", "Pocket"); self.pk.Length, self.pk.Width, self.pk.Height = 10, 22, 3
        self.pk.Placement = App.Placement(V(10, -1, 7), App.Rotation())
        self.pin = d.addObject("PartDesign::Body", "Pin")
        self.sk = self.pin.newObject("Sketcher::SketchObject", "PinSketch")
        self.sk.AttachmentSupport = [(self.pin.Origin.OriginFeatures[3], "")]; self.sk.MapMode = "FlatFace"
        if hexagon:
            self.hexagon(0)
        else:
            self.sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5))
        pad = self.pin.newObject("PartDesign::Pad", "PinPad"); pad.Profile = self.sk; pad.Length = 20
        d.recompute()
        a = self.asm = d.addObject("Assembly::AssemblyObject", "Assembly"); a.Type = "Assembly"
        self.jg = a.newObject("Assembly::JointGroup", "Joints")
        self.lb = a.newObject("App::Link", "BlkI"); self.lb.LinkedObject = self.blk
        self.lp = a.newObject("App::Link", "PinI"); self.lp.LinkedObject = self.pin
        self.lp.Placement = App.Placement(V(60, 40, 0), App.Rotation())
        d.recompute()
        g = self.jg.newObject("App::FeaturePython", "G"); JointObject.GroundedJoint(g, self.lb)
        tb, bp = self.face(self.blk.Shape, 10, 1), self.face(self.pin.Shape, 0, -1)
        j = self.j = self.jg.newObject("App::FeaturePython", "Fastened1"); JointObject.Joint(j, 0)
        picks = [[self.lp, [bp, bp]], [self.lb, [tb, tb]]]
        j.Proxy.setJointConnectors(j, picks if pinFirst else picks[::-1])
        self.solve()
        edge = [f"Edge{i}" for i, e in enumerate(self.blk.Shape.Edges, 1)
                if all(abs(v.Point.z) < 1e-7 and abs(v.Point.y) < 1e-7 for v in e.Vertexes)][0]
        self.pat = AssemblyPattern.makePattern(a, "Linear", [self.lp], (self.lb, [edge]))
        self.pat.Count, self.pat.Distance = count, 25
        self.solve()

    def hexagon(self, deg):
        self.sk.deleteAllGeometry()
        t = math.radians(deg)
        pts = [V(5 * math.cos(math.pi / 3 * k + t), 5 * math.sin(math.pi / 3 * k + t), 0) for k in range(6)]
        for k in range(6):
            self.sk.addGeometry(Part.LineSegment(pts[k], pts[(k + 1) % 6]))

    def rotateHexagon(self, deg):
        """In place (geometry tags kept): the 6 segments turned about the origin"""
        t = math.radians(deg)
        geo = self.sk.Geometry
        pts = [V(5 * math.cos(math.pi / 3 * k + t), 5 * math.sin(math.pi / 3 * k + t), 0) for k in range(6)]
        for k in range(6):
            geo[k].StartPoint, geo[k].EndPoint = pts[k], pts[(k + 1) % 6]
        self.sk.Geometry = geo

    @staticmethod
    def face(s, z, nz):
        return [f"Face{i}" for i, f in enumerate(s.Faces, 1) if f.Surface.TypeId == "Part::GeomPlane"
                and abs(f.CenterOfMass.z - z) < 1e-6 and f.normalAt(0, 0).z * nz > 0.5][0]

    def solve(self):
        self.d.recompute(); rc = self.asm.solve(); self.d.recompute(); return rc

    def valid(self, j):
        try:
            return bool(j.isValid())
        except Exception as e:
            return f"exc {e}"

    def state(self, tag, *joints):
        cs = sorted((c for c in self.pat.Instances if c), key=lambda c: c.PatternIndex)
        js = joints or (self.j,)
        print(f"  {tag}: pin bottom {r3(self.lp.Placement.Base)} up {r3(self.lp.Placement.Rotation.multVec(V(0, 0, 1)))}"
              f" | copies {len(cs)} x {[round(c.Placement.Base.x, 2) for c in cs][:6]}"
              f" | mates {[ (x.Label, self.valid(x)) for x in js]} | pattern {self.pat.State}")

    def close(self):
        App.closeDocument(self.d.Name)


print("AR6: offset Z +3 (Onshape: bottom z 7, 3 into Blk, x 6 y 10, either pick order)")
for first in (True, False):
    m = M("AR6" + "PB"[first], pinFirst=first)
    m.state("Pin first" if first else "Blk first")
    m.j.Offset2 = App.Placement(V(0, 0, 3), App.Rotation()); m.solve()
    m.state("offset +3")
    if first:
        print("AR6b: Fillet1 suppressed (Onshape: x 5, keeps z 7, copies shift alike)")
        m.fil.Suppressed = True; m.solve(); m.state("fillet off")
        m.fil.Suppressed = False; m.solve(); m.state("fillet on")
        print("AR10: Fillet1 moved after the Pocket (Onshape: OK, Pin stays x 6, top x 2..10)")
        try:
            m.blk.removeObject(m.fil); m.blk.insertObject(m.fil, m.pk, True)
            m.fil.Base = (m.pk, [e for e in m.fil.Base[1]])
            m.solve()
            print("   order", [o.Name for o in m.blk.Group if o.isDerivedFrom("PartDesign::Feature")], "tip", m.blk.Tip.Name,
                  "fillet valid", m.fil.isValid(), "Blk V", round(m.blk.Shape.Volume, 4))
            m.state("reordered")
        except Exception as e:
            print("   reorder exc", e)
    m.close()

print("AR7: a pattern copy grounded, then spacing 25 -> 30 (Onshape: the copy moves anyway, all at 30, no error)")
m = M("AR7")
c3 = sorted(m.pat.Instances, key=lambda c: c.PatternIndex)[1]
try:
    g3 = m.jg.newObject("App::FeaturePython", "G3"); JointObject.GroundedJoint(g3, c3); m.solve()
    print("   grounded", c3.Label, "at", r3(c3.Placement.Base))
    m.pat.Distance = 30; rc = m.solve()
    print("   solve", rc, c3.Label, "at", r3(c3.Placement.Base))
    m.state("spacing 30")
except Exception as e:
    print("   exc", e)
m.close()

print("AR11: count 6 -> 1 -> 100 (Onshape: OK; 100 at the spacing)")
m = M("AR11")
m.pat.Count = 1; m.solve(); m.state("count 1")
import time; t = time.time(); m.pat.Count = 100; m.solve(); dt = time.time() - t
m.state(f"count 100 ({dt:.2f} s)")
cs = sorted(m.pat.Instances, key=lambda c: c.PatternIndex); print("   last copy x", round(cs[-1].Placement.Base.x, 2) if cs else None)
m.close()

print("AR9: hexagon Pin; Parallel between a flat (normal -y) and Blk's front face; then the hexagon turned 15 deg"
      " (Onshape: both mates ERROR 'overdefines', Pin unmoved)")
m = M("AR9", hexagon=True)
flat = [f"Face{i}" for i, f in enumerate(m.pin.Shape.Faces, 1) if f.Surface.TypeId == "Part::GeomPlane" and f.normalAt(0, 0).y < -0.99][0]
front = [f"Face{i}" for i, f in enumerate(m.blk.Shape.Faces, 1) if f.Surface.TypeId == "Part::GeomPlane" and f.normalAt(0, 0).y < -0.99][0]
p = m.jg.newObject("App::FeaturePython", "Parallel1"); JointObject.Joint(p, JointObject.JointTypes.index("Parallel"))
p.Proxy.setJointConnectors(p, [[m.lp, [flat, flat]], [m.lb, [front, front]]])
rc = m.solve(); print("   solve", rc, "redundant", m.asm.RedundantJoints); m.state("parallel", m.j, p)
before = m.lp.Placement
m.rotateHexagon(15); rc = m.solve()
print("   solve", rc, "| redundant", m.asm.RedundantJoints,
      "| pin rotation now", round(m.lp.Placement.Rotation.Angle * 180 / math.pi, 3), "deg (was", round(before.Rotation.Angle * 180 / math.pi, 3), ")")
flatN = [f.normalAt(0, 0) for f in Part.getShape(m.lp).Faces if f.Surface.TypeId == "Part::GeomPlane" and abs(f.normalAt(0, 0).z) < 0.1]
print("   pin side normals", [r3(n) for n in flatN][:2])
m.state("turned 15", m.j, p)
m.close()
