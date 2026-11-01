# Review probes for naming-class-D section 11 (rigid turns): a closure that reads rigid while a
# geometry source outside it (the Body's origin axis or plane) stays. Placement route: the chain's
# frame turns with the part (M_local = I), so today's verdict on feature3 is the rule's verdict.
# Expectations follow 10.1's convention (global geometry unchanged: the references stay).

import math

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex

V = App.Vector
X = V(1, 0, 0)
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
        # the point's place checked: a coaxial wall or a concentric rim gives the same point, and
        # the solver keeps such a trade as equivalent
        return owner, Attached()

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
        body.Tip = self.mirror  # newObject() leaves a Mirrored out of the chain: it never computes
        return self.mirror

    def move(self, doc):
        self.base.Placement = self.motion


class ReviewQuarterRevolveFlipped(Scenario):
    """Round 1's T1 (review pr557o-r1): a line locus keeps its sense. A rectangle x 2..4, z -5..5
    in the XZ plane, revolved 90 degrees about the Body's Z axis (a quarter of a tube, 10 high).
    The sketch is attached FlatFace to the XZ plane; the edit turns its AttachmentOffset 180
    degrees about its own X axis (the global X axis): the rectangle lands on itself (its top line
    where its bottom line was), the revolve sweeps the same quarter, the solid is unchanged. The
    turn maps the Z axis onto itself reversed, and a partial revolve reads the axis's sense: not
    rigid. Convention 10.1: the references stay."""

    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r1"
    TIER = "F"
    REFS = ("top", "bottom", "inner_wall", "outer_wall")

    def point(self, name):
        c, s = math.cos(math.radians(45)), math.sin(math.radians(45)) * self.sy
        return {
            "top": ("plane", V(3 * c, 3 * s, 5)),
            "bottom": ("plane", V(3 * c, 3 * s, -5)),
            "inner_wall": ("cylinder", V(2 * c, 2 * s, 0)),
            "outer_wall": ("cylinder", V(4 * c, 4 * s, 0)),
        }[name]

    def expect(self, name):
        kind, p = self.point(name)
        return face(surface=kind, contains=p)

    def profile(self, doc, body):
        sketch = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(sketch)
        sketch.AttachmentSupport = [(originFeature(body, "XZ_Plane"), "")]
        sketch.MapMode = "FlatFace"
        return sketch

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = self.profile(doc, body)
        pts = [V(2, -5, 0), V(4, -5, 0), V(4, 5, 0), V(2, 5, 0), V(2, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.rev = body.newObject("PartDesign::Revolution", "Rev")
        self.rev.Profile = self.base
        self.rev.ReferenceAxis = (originFeature(body, "Z_Axis"), [""])
        self.rev.Angle = 90
        doc.recompute()
        box = self.rev.Shape.BoundBox
        self.sy = 1.0 if box.YMax > 1.0 else -1.0
        assert abs(box.ZMin + 5) < 1e-6 and abs(box.ZMax - 5) < 1e-6, box
        for name in self.REFS:
            kind = self.point(name)[0]
            element = self.names(self.rev, self.expect(name))[0]
            if kind == "plane":
                owner = doc.addObject("Sketcher::SketchObject", name)
                body.addObject(owner)
                owner.AttachmentSupport = [(self.rev, element)]
                owner.MapMode = "FlatFace"
            else:
                owner = body.newObject("PartDesign::Point", name)
                owner.AttachmentSupport = [(self.rev, element)]
                owner.MapMode = "CenterOfMass"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def flip(self, doc):
        self.base.AttachmentOffset = App.Placement(V(), App.Rotation(X, 180))

    def edit(self, doc):
        self.flip(doc)
        doc.recompute()
        box = self.rev.Shape.BoundBox
        # the solid is unchanged globally: the same quarter, the same height
        assert (box.YMax > 1.0) == (self.sy > 0) and abs(box.ZMax - 5) < 1e-6, box


class ReviewQuarterRevolveFlippedFree(ReviewQuarterRevolveFlipped):
    """The same with an unattached sketch whose own Placement turns (the chain's frame turns with
    it: M_local = I)."""

    def profile(self, doc, body):
        sketch = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(sketch)
        sketch.Placement = App.Placement(V(), App.Rotation(X, 90))  # XZ, local y up
        return sketch

    def flip(self, doc):
        self.base.Placement = App.Placement(V(), App.Rotation(X, 180)).multiply(self.base.Placement)


class ReviewDraftedBoxFlipped(Scenario):
    """Round 1's T2 (review pr557o-r1): the Body's origin named through a Draft's NeutralPlane and
    PullDirection is a locus. A rectangle 20 x 10 centred at the origin on the XY plane (sketch
    attached FlatFace), padded symmetric 10 high (z -5..5); a Draft of its four sides, 5 degrees,
    neutral plane the Body's XY plane, pull direction its Z axis: top and bottom differ in size.
    The edit turns the sketch's AttachmentOffset 180 degrees about its X axis: the rectangle lands
    on itself, the pad is the same box, the draft the same solid, and the pad's top and bottom
    (and its +y and -y sides) trade names. The turn reverses the pull direction: not rigid.
    Convention 10.1: the references stay."""

    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r1"
    TIER = "F"
    REFS = ("top", "bottom", "side_py", "side_px")
    POINTS = {
        "top": (0, 0, 5),
        "bottom": (0, 0, -5),
        "side_py": (0, 5, 0),
        "side_px": (10, 0, 0),
    }

    def expect(self, name):
        return face(surface="plane", contains=V(*self.POINTS[name]))

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0), V(-10, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        pad.Midplane = True
        doc.recompute()
        sides = [
            self.names(pad, face(surface="plane", contains=p))[0]
            for p in (V(10, 0, 0), V(-10, 0, 0), V(0, 5, 0), V(0, -5, 0))
        ]
        self.draft = body.newObject("PartDesign::Draft", "Draft")
        self.draft.Base = (pad, sides)
        self.draft.Angle = 5
        self.draft.NeutralPlane = (originFeature(body, "XY_Plane"), [""])
        self.draft.PullDirection = (originFeature(body, "Z_Axis"), [""])
        body.Tip = self.draft
        doc.recompute()
        box = self.draft.Shape.BoundBox
        assert self.draft.Shape.isValid() and abs(box.ZMax - 5) < 1e-6, box
        for name in self.REFS:
            element = self.names(self.draft, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(self.draft, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())
        assert abs(self.areaAt(5) - self.areaAt(-5)) > 1e-3

    def edit(self, doc):
        self.base.AttachmentOffset = App.Placement(V(), App.Rotation(X, 180))
        doc.recompute()

    def areaAt(self, z):
        faces = [f for f in self.draft.Shape.Faces if abs(f.CenterOfMass.z - z) < 1e-6]
        assert len(faces) == 1, faces
        return faces[0].Area
