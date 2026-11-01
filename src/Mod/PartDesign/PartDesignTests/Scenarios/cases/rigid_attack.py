# Review probes for naming-class-D section 11 (rigid turns): a closure that reads rigid while a
# geometry source outside it (the Body's origin axis or plane) stays. Placement route: the chain's
# frame turns with the part (M_local = I), so today's verdict on feature3 is the rule's verdict.
# Expectations follow 10.1's convention (global geometry unchanged: the references stay).

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex

V = App.Vector
Z = V(0, 0, 1)


def originFeature(body, role):
    return [f for f in body.Origin.OriginFeatures if role in (getattr(f, "Role", ""), f.Name)][0]


class AttackBase(Scenario):
    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    ISSUE = "ops#557"
    FOUND_BY = "reviewer rigid turns"
    TIER = "F"
    STAY = ()
    FOLLOW = {}
    motion = App.Placement()
    REFS = ()
    ELEMENTS = {}

    def where(self, pt, name):
        if self.stepName and name in self.FOLLOW:
            return V(*self.FOLLOW[name])
        if self.stepName and name not in self.STAY:
            return self.motion.multVec(V(*pt))
        return V(*pt)

    def expect(self, name):
        kind, pt = self.ELEMENTS[name]
        p = self.where(pt, name)
        if kind == "arc":
            return edge(curve="circle", contains=p)
        if kind == "line":
            return edge(curve="line", contains=p)
        if kind == "plane":
            return face(surface="plane", contains=p)
        if kind == "cylinder":
            return face(surface="cylinder", contains=p)
        return vertex(p)

    def consumer(self, doc, body, name, target):
        kind = self.ELEMENTS[name][0]
        element = self.names(target, self.expect(name))[0]
        if kind == "plane":
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(target, element)]
            owner.MapMode = "FlatFace"
            return owner, Attached()
        owner = body.newObject("PartDesign::Point", name)
        owner.AttachmentSupport = [(target, element)]
        owner.MapMode = "Vertex" if kind == "vertex" else "CenterOfMass"
        return owner, None

    def build(self, doc):
        self.body = doc.addObject("PartDesign::Body", "Body")
        last = self.model(doc, self.body)
        doc.recompute()
        for name in self.REFS:
            owner, outcome = self.consumer(doc, self.body, name, last)
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), outcome)

    def edit(self, doc):
        self.move(doc)


class AttackRevolveTurnedOnItself(AttackBase):
    """A rectangle (x 2..4, z 0..10 in the XZ plane) revolved 360 about the Body's Z axis: a tube.
    The sketch's Placement turns 180 degrees about the rectangle's centre, in its plane: the
    rectangle lands on itself (its inner line where the outer was), the axis is not a placement
    source, the closure (the sketch alone) reads rigid, the tube is unchanged. Convention 10.1:
    the references stay."""
    motion = App.Placement()  # the geometry is unchanged: every reference stays
    REFS = ("inner_wall", "outer_wall", "top", "bottom")
    ELEMENTS = {
        "inner_wall": ("cylinder", (2, 0, 5)),
        "outer_wall": ("cylinder", (4, 0, 5)),
        "top": ("plane", (3, 0, 10)),
        "bottom": ("plane", (3, 0, 0)),
    }

    def model(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # XZ
        pts = [V(2, 0, 0), V(4, 0, 0), V(4, 10, 0), V(2, 10, 0), V(2, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.rev = body.newObject("PartDesign::Revolution", "Rev")
        self.rev.Profile = self.base
        self.rev.ReferenceAxis = (originFeature(body, "Z_Axis"), [""])
        self.rev.Angle = 360
        return self.rev

    def move(self, doc):
        turn = App.Placement(V(6, 10, 0), App.Rotation(Z, 180))  # about local (3, 5)
        self.base.Placement = self.base.Placement.multiply(turn)


class AttackRevolveTurnedOnItselfSketchAxis(AttackRevolveTurnedOnItself):
    """Control: the same, revolved about the sketch's own V axis (which turns with the sketch):
    the tube turns onto itself as one piece; decision 212: the references follow."""
    REFS = ("inner_wall", "outer_wall", "top", "bottom")
    FOLLOW = {"inner_wall": (4, 0, 5), "outer_wall": (2, 0, 5), "top": (3, 0, 0), "bottom": (3, 0, 10)}

    def model(self, doc, body):
        AttackRevolveTurnedOnItself.model(self, doc, body)
        self.rev.ReferenceAxis = (self.base, ["V_Axis"])
        return self.rev


class AttackHolesOnAxisTurned(AttackBase):
    """The box x 0..20, y -2..8 (centre (10, 3)), two holes on the Body's X axis at x = 5 and 15,
    the holes' sketch attached ObjectXY to the Pad (it turns with the part) with the X axis as
    external geometry: the circles' centres on it, x fixed from the sketch's origin. The base
    sketch's Placement turns 180 about the centre: the box lands on itself, the sketch solver
    keeps the holes on the global axis (they trade places), the closure reads rigid, the geometry
    is unchanged. Convention 10.1: the references stay."""
    motion = App.Placement(V(20, 6, 0), App.Rotation(Z, 180))
    STAY = ("hole1_rim", "hole1_wall")
    REFS = ("hole1_rim", "hole1_wall", "end_x0", "corner_000")
    ELEMENTS = {
        "hole1_rim": ("arc", (6.5, 0, 10)),
        "hole1_wall": ("cylinder", (6.5, 0, 5)),
        "end_x0": ("plane", (0, 3, 5)),
        "corner_000": ("vertex", (0, -2, 0)),
    }

    def model(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        pts = [V(0, -2, 0), V(20, -2, 0), V(20, 8, 0), V(0, 8, 0), V(0, -2, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.AttachmentSupport = [(self.block, "")]
        self.holes.MapMode = "ObjectXY"
        self.holes.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        doc.recompute()
        self.holes.addExternal(originFeature(body, "X_Axis").Name, "")
        c0 = self.holes.addGeometry(Part.Circle(V(5, 0, 0), Z, 1.5), False)
        c1 = self.holes.addGeometry(Part.Circle(V(15, 0, 0), Z, 1.5), False)
        self.holes.addConstraint(Sketcher.Constraint("Radius", c0, 1.5))
        self.holes.addConstraint(Sketcher.Constraint("Radius", c1, 1.5))
        self.holes.addConstraint(Sketcher.Constraint("PointOnObject", c0, 3, -3))
        self.holes.addConstraint(Sketcher.Constraint("PointOnObject", c1, 3, -3))
        self.holes.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, c0, 3, 5.0))
        self.holes.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, c1, 3, 15.0))
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holes
        self.pocket.Type = 1
        return self.pocket

    def move(self, doc):
        self.base.Placement = self.motion


class AttackMirrorTurnedAboutCentre(AttackBase):
    """The two-hole box (y 0..10, holes at (5, 5) and (15, 5), their sketch ObjectXY on the Pad)
    mirrored about the Body's XZ plane; the base sketch's Placement turns 180 about the box's
    centre: the box lands on itself and so does its mirror image (the plane is not a placement
    source; the closure reads rigid); the geometry is unchanged. Convention 10.1: the references
    into the mirror image stay."""
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    STAY = ("mhole1_rim", "mcorner", "mend_x0", "medge_y")
    REFS = ("mhole1_rim", "mcorner", "mend_x0", "medge_y", "hole1_rim")
    FOLLOW = {"hole1_rim": (16.5, 5, 10)}  # the box's own hole follows the part (212)
    ELEMENTS = {
        "mhole1_rim": ("arc", (6.5, -5, 10)),
        "mcorner": ("vertex", (0, -10, 0)),
        "mend_x0": ("plane", (0, -5, 5)),
        "medge_y": ("line", (10, -10, 10)),
        "hole1_rim": ("arc", (6.5, 5, 10)),
    }

    def model(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.addGeometry(Part.Circle(V(5, 5, 0), Z, 1.5), False)
        self.holes.addGeometry(Part.Circle(V(15, 5, 0), Z, 1.5), False)
        self.holes.AttachmentSupport = [(self.block, "")]
        self.holes.MapMode = "ObjectXY"
        self.holes.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holes
        self.pocket.Type = 1
        doc.recompute()
        self.mirror = body.newObject("PartDesign::Mirrored", "Mirror")
        self.mirror.Originals = [self.block, self.pocket]
        self.mirror.MirrorPlane = (originFeature(body, "XZ_Plane"), [""])
        return self.mirror

    def move(self, doc):
        self.base.Placement = self.motion
