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


class ReviewPadCustomDirectionFlipped(Scenario):
    """A rectangle x -10..10, y -5..5 on the Body's XY plane (FlatFace, AttachmentOffset), padded
    10 high along a CUSTOM direction (0, 0, 1) fixed in the Body (UseCustomVector, not the sketch's
    normal). The edit turns the AttachmentOffset 180 degrees about the X axis: the rectangle lands
    on itself (its +y line at -y), the custom direction does not turn, so the pad is the same solid
    (z 0..10): the model is unchanged globally and the part was not moved as one piece (the pad's
    direction stayed). Convention 10.1: the references stay (the +y wall is still the +y wall)."""
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557s-r2"
    TIER = "F"
    REFS = ("side_py", "side_my", "top", "bottom")
    POINTS = {"side_py": (0, 5, 5), "side_my": (0, -5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}

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
        pad.UseCustomVector = True
        pad.AlongSketchNormal = False
        pad.Direction = V(0, 0, 1)
        doc.recompute()
        box = pad.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box
        self.pad = pad
        for name in self.REFS:
            element = self.names(pad, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(pad, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.base.AttachmentOffset = App.Placement(V(), App.Rotation(X, 180))
        doc.recompute()
        box = self.pad.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box


class ReviewPadCustomDirectionFlippedPlacement(ReviewPadCustomDirectionFlipped):
    """The same with the base sketch unattached and its own Placement turned 180 about the X axis
    (the chain's frame turns: M_local = I)."""

    def build(self, doc):
        ReviewPadCustomDirectionFlipped.build(self, doc)

    def edit(self, doc):
        self.base.Placement = App.Placement(V(), App.Rotation(X, 180))
        doc.recompute()
        box = self.pad.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box


class ReviewPadCustomDirectionFlippedAtZ1(Scenario):
    """A rectangle x -10..10, y -5..5 on the Body's XY plane lifted to z 1 (AttachmentOffset
    (0, 0, 1)), padded 10 along a CUSTOM direction (0, 0, 1) fixed in the Body (UseCustomVector,
    AlongSketchNormal off): the pad is z 1..11. The edit turns the sketch over about its own X axis
    (AttachmentOffset (0, 0, 1), 180 about X): the rectangle lands on itself (its +y line at -y),
    the custom direction stays, so the pad is the same solid z 1..11 (globally unchanged, the part
    did not move as one piece). The sketch's motion M is the half turn about the line y 0, z 1; the
    direction's tip (0, 0, 1) lies on that line, so M v = v and the vector check passes as a point.
    Convention 10.1: every reference stays (the +y wall is still the +y wall)."""
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2b"
    TIER = "F"
    lift = 1.0
    direction = (0, 0, 1)
    REFS = ("side_py", "side_my", "top", "bottom")

    def points(self):
        h = self.lift
        return {"side_py": (0, 5, h + 5), "side_my": (0, -5, h + 5), "top": (0, 0, h + 10),
                "bottom": (0, 0, h)}

    def expect(self, name):
        return face(surface="plane", contains=V(*self.points()[name]))

    def check(self):
        box = self.pad.Shape.BoundBox
        assert abs(box.ZMin - self.lift) < 1e-6 and abs(box.ZMax - self.lift - 10) < 1e-6, box
        assert abs(box.YMin + 5) < 1e-6 and abs(box.YMax - 5) < 1e-6, box

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        self.base.AttachmentOffset = App.Placement(V(0, 0, self.lift), App.Rotation())
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0), V(-10, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        pad.UseCustomVector = True
        pad.AlongSketchNormal = False
        pad.Direction = V(*self.direction)
        doc.recompute()
        self.pad = pad
        self.check()
        for name in self.REFS:
            element = self.names(pad, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(pad, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.base.AttachmentOffset = App.Placement(V(0, 0, self.lift), App.Rotation(X, 180))
        doc.recompute()
        self.check()


class ReviewPadTiltedDirectionFlippedAtZ06(ReviewPadCustomDirectionFlippedAtZ1):
    """The same with a tilted custom direction (0.8, 0, 0.6) (unit) and the sketch at z 0.6: the
    tip lies on the turn's line (y 0, z 0.6). The pad is a slanted prism; its y walls stay y +-5,
    its bottom stays z 0.6. Convention 10.1: the references stay."""
    lift = 0.6
    direction = (0.8, 0, 0.6)
    REFS = ("side_py", "side_my", "bottom")

    def points(self):
        h = self.lift
        return {"side_py": (4, 5, h + 3), "side_my": (4, -5, h + 3), "bottom": (0, 0, h)}

    def check(self):
        box = self.pad.Shape.BoundBox
        assert abs(box.ZMin - self.lift) < 1e-6, box
        assert abs(box.YMin + 5) < 1e-6 and abs(box.YMax - 5) < 1e-6, box


class ReviewPadCustomDirectionFlippedAtZ0(ReviewPadCustomDirectionFlippedAtZ1):
    """Control: the PR's own ReviewPadCustomDirectionFlipped shape (sketch at z 0, built here the
    same way): M v = -v, the vector check fails."""
    lift = 0.0


class ReviewPadCustomDirectionFlippedAtZ1Free(ReviewPadCustomDirectionFlippedAtZ1):
    """The same with the base sketch unattached (MapMode Deactivated, Placement (0, 0, 1)) and the
    edit turning its own Placement 180 about its X axis."""

    def build(self, doc):
        ReviewPadCustomDirectionFlippedAtZ1.build(self, doc)
        self.base.AttachmentSupport = []
        self.base.MapMode = "Deactivated"
        self.base.Placement = App.Placement(V(0, 0, self.lift), App.Rotation())
        doc.recompute()
        self.check()

    def edit(self, doc):
        self.base.Placement = App.Placement(V(0, 0, self.lift), App.Rotation(X, 180))
        doc.recompute()
        self.check()


class ReviewPadCustomDirectionFlippedAtZ0Free(ReviewPadCustomDirectionFlippedAtZ1Free):
    """Control for the unattached route: the sketch at z 0 (M v = -v)."""
    lift = 0.0


# Round 2c's review cases (pr557s-r2c, pr557o-r2c, at 4fb8af4bbe): a turn made in the same recompute
# as another edit the record didn't see. A pad's Reversed ticked (R2), the axis line of a revolve or
# of a pad's ReferenceAxis redrawn or dragged to keep its old sense (F-A, R1), UseCustomVector
# switched: the part did not move as one piece. Decision 231: a turn reads rigid only if nothing else
# changed, every object's digest of its other inputs as it was; otherwise the frame rule (211)
# decides, loud. Expectations follow convention 10.1 (global geometry unchanged: the references stay)
# or, for a part turned as one piece, decision 212 (they follow).

FLIP_X = App.Placement(V(0, 0, 0), App.Rotation(X, 180))


def flipped(p):
    """A point after the half turn about the global X axis."""
    return (p[0], -p[1], -p[2])


class R2cPadBase(Scenario):
    """A rectangle x -10..10, y -5..5 on the Body's XY plane (FlatFace), padded 10 (the pad's own
    direction: the sketch normal, or a sketch line's). The edit turns the base sketch (and any
    other change the case names). References: the +y wall, the top and the bottom cap, each a
    sketch attached to the face. Expectations follow convention 10.1 (global geometry unchanged:
    the references stay) or, for a part turned as one piece, decision 212 (they follow)."""

    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557s-r2c"
    TIER = "F"
    REFS = ("side_py", "top", "bottom")
    BEFORE = {"side_py": (0, 5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}
    AFTER = None  # None: the references stay

    def point(self, name):
        if self.stepName and self.AFTER is not None:
            return V(*self.AFTER[name])
        return V(*self.BEFORE[name])

    def expect(self, name):
        return face(surface="plane", contains=self.point(name))

    def profile(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0), V(-10, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)

    def pad(self, doc, body):
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        return pad

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.profile(doc, body)
        self.pad_ = self.pad(doc, body)
        doc.recompute()
        assert self.pad_.isValid(), self.pad_.getStatusString()
        box = self.pad_.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box
        for name in self.REFS:
            element = self.names(self.pad_, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(self.pad_, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.base.AttachmentOffset = FLIP_X
        self.edited(doc)
        doc.recompute()
        if not self.pad_.isValid():
            return  # its axis reference broke (the line drawn again): the references show it
        box = self.pad_.Shape.BoundBox
        top = 10 if self.AFTER is None else max(self.AFTER["top"][2], self.AFTER["bottom"][2])
        assert abs(box.ZMax - top) < 1e-6, (box, top)

    def edited(self, doc):
        pass


class R2cPadAxisLineBase(R2cPadBase):
    """The pad's direction from a sketch line (ReferenceAxis = AxisSketch Edge1), the line drawn
    local (0, -5) -> (0, 5) on a sketch attached to the XZ plane: global +Z."""

    abstract = True
    redraw = True
    construction = False
    sub = "Edge1"

    def pad(self, doc, body):
        self.axis = doc.addObject("Sketcher::SketchObject", "AxisSketch")
        body.addObject(self.axis)
        self.axis.AttachmentSupport = [(originFeature(body, "XZ_Plane"), "")]
        self.axis.MapMode = "FlatFace"
        self.axis.addGeometry(Part.LineSegment(V(0, -5, 0), V(0, 5, 0)), self.construction)
        doc.recompute()
        pad = R2cPadBase.pad(self, doc, body)
        pad.UseCustomVector = False
        pad.ReferenceAxis = (self.axis, [self.sub])
        return pad

    def edited(self, doc):
        self.axis.AttachmentOffset = FLIP_X
        if self.redraw:
            self.axis.deleteAllGeometry()
            self.axis.addGeometry(Part.LineSegment(V(0, 5, 0), V(0, -5, 0)), self.construction)


class R2cPadAxisLineFlipRedrawn(R2cPadAxisLineBase):  # the line is a real one on AxisSketch
    """Both sketches' AttachmentOffsets turn 180 about X (one motion for every placement source)
    and the axis line is redrawn reversed: the axis stays global +Z while the base sketch's normal
    turns to -Z. The pad is the same solid (z 0..10), the walls and caps stay."""


class R2cPadAxisLineFlipOnly(R2cPadAxisLineBase):
    """Control: the same turn without the redraw: the axis turns to -Z with the sketch, the pad is
    z -10..0: the part turned as one piece. The references follow the turn (decision 212)."""

    redraw = False
    AFTER = {
        "side_py": flipped((0, 5, 5)),
        "top": flipped((0, 0, 10)),
        "bottom": flipped((0, 0, 0)),
    }


class R2cPadReversedFlip(R2cPadBase):
    """The pad's own direction is the sketch normal. The edit turns the base sketch 180 about X
    (the normal becomes -Z) and sets Reversed: the pad still goes up, the same solid (z 0..10)."""

    def edited(self, doc):
        self.pad_.Reversed = True


class R2cPadCustomOn(R2cPadBase):
    """The pad starts on the sketch normal. The edit turns the base sketch 180 about X and turns
    UseCustomVector on with the direction (0, 0, 1): the pad goes up, the same solid."""

    def edited(self, doc):
        self.pad_.UseCustomVector = True
        self.pad_.AlongSketchNormal = False
        self.pad_.Direction = Z


class R2cPadCustomOff(R2cPadBase):
    """The pad starts with the custom direction (0, 0, 1). The edit turns the base sketch 180 about
    X and turns UseCustomVector off: the pad goes along the new normal (-Z), z -10..0: the part
    turned as one piece. The references follow the turn (decision 212)."""

    AFTER = {
        "side_py": flipped((0, 5, 5)),
        "top": flipped((0, 0, 10)),
        "bottom": flipped((0, 0, 0)),
    }

    def pad(self, doc, body):
        pad = R2cPadBase.pad(self, doc, body)
        pad.UseCustomVector = True
        pad.AlongSketchNormal = False
        pad.Direction = Z
        return pad

    def edited(self, doc):
        self.pad_.UseCustomVector = False


class R2cRevAxisBase(Scenario):
    """A rectangle x 2..4, y -5..5 on the XZ plane (FlatFace), revolved 90 degrees about the line
    of an axis sketch (attached to the XZ plane, drawn local (0, -5) -> (0, 5): the global Z axis).
    The edit turns both sketches 180 about X; the quarter's references: the caps and the walls."""

    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557s-r2c"
    TIER = "F"
    REFS = ("top", "bottom", "inner_wall", "outer_wall")
    redraw = True
    follows = False
    construction = True
    sub = "Axis0"
    inSketch = True

    def point(self, name):
        c, s = math.cos(math.radians(45)), math.sin(math.radians(45)) * self.sy
        p = {
            "top": ("plane", (3 * c, 3 * s, 5)),
            "bottom": ("plane", (3 * c, 3 * s, -5)),
            "inner_wall": ("cylinder", (2 * c, 2 * s, 0)),
            "outer_wall": ("cylinder", (4 * c, 4 * s, 0)),
        }[name]
        if self.stepName and self.follows:
            return p[0], V(*flipped(p[1]))
        return p[0], V(*p[1])

    def expect(self, name):
        kind, p = self.point(name)
        return face(surface=kind, contains=p)

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XZ_Plane"), "")]
        self.base.MapMode = "FlatFace"
        pts = [V(2, -5, 0), V(4, -5, 0), V(4, 5, 0), V(2, 5, 0), V(2, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        if self.inSketch:
            self.axis = self.base
        else:
            self.axis = doc.addObject("Sketcher::SketchObject", "AxisSketch")
            body.addObject(self.axis)
            self.axis.AttachmentSupport = [(originFeature(body, "XZ_Plane"), "")]
            self.axis.MapMode = "FlatFace"
        self.axisIndex = self.axis.addGeometry(
            Part.LineSegment(V(0, -5, 0), V(0, 5, 0)), self.construction
        )
        doc.recompute()
        self.rev = body.newObject("PartDesign::Revolution", "Rev")
        self.rev.Profile = self.base
        self.rev.ReferenceAxis = (self.axis, [self.sub])
        self.rev.Angle = 90
        doc.recompute()
        assert self.rev.isValid(), self.rev.getStatusString()
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

    def edit(self, doc):
        self.base.AttachmentOffset = FLIP_X
        self.axis.AttachmentOffset = FLIP_X
        if self.redraw:
            self.axis.delGeometry(self.axisIndex)
            self.axisIndex = self.axis.addGeometry(
                Part.LineSegment(V(0, 5, 0), V(0, -5, 0)), self.construction
            )
        doc.recompute()
        if not self.rev.isValid():
            return  # its axis reference broke (the line drawn again): the references show it
        box = self.rev.Shape.BoundBox
        if not self.follows:
            assert (box.YMax > 1.0) == (self.sy > 0) and abs(box.ZMax - 5) < 1e-6, box
        else:
            assert (box.YMax > 1.0) == (self.sy < 0), box


class R2cRevAxisLineFlipRedrawn(R2cRevAxisBase):
    """The axis line is redrawn reversed as both sketches turn: the axis stays global +Z while the
    profile's sketch turns over (ReviewQuarterRevolveFlipped through a sketch line instead of the
    origin axis). The solid is unchanged: the references stay."""


class R2cRevAxisLineFlipOnly(R2cRevAxisBase):
    """Control: the same turn without the redraw: the axis turns with the profile, the quarter is
    the mirrored one (the part turned as one piece): the references follow."""

    redraw = False
    follows = True


class R2cRevAxisEdgeFlipRedrawn(R2cRevAxisLineFlipRedrawn):
    """The same with the axis a real line on a second sketch (AxisSketch), the revolve's
    ReferenceAxis its Edge1: the reference to the line is an element reference of its own."""

    construction = False
    sub = "Edge1"
    inSketch = False


class RevPadAxisLineRedrawnBothFlipped(Scenario):
    """A rectangle x -10..10, y -5..5 in an unattached sketch Base at the body's origin, padded 10
    along a REFERENCE AXIS (UseCustomVector off): the line (0,0,0)->(0,0,10) of a second unattached
    sketch AxisSketch lying in the XZ plane (Placement 90 about X). The pad is z 0..10. The edit
    turns BOTH sketches over by the same half turn M about the global X axis (Base's Placement,
    AxisSketch's Placement M*P) and redraws the axis line's end point so that the line still runs
    (0,0,0)->(0,0,10) globally: the pad is the same solid z 0..10 (the part did not move as one
    piece: its direction stayed in the body). Every placement source moved by M; the pad's
    Direction (0,0,1) stayed, but it is read-only and left out of the record.
    Convention 10.1: every reference stays (the +y wall is still the +y wall)."""
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2c"
    TIER = "F"
    REFS = ("side_py", "side_my", "top", "bottom")
    redraw = "move"  # move the line's end point; "replace": delete the line and draw it again

    def points(self):
        return {"side_py": (0, 5, 5), "side_my": (0, -5, 5), "top": (0, 0, 10), "bottom": (0, 0, 0)}

    def expect(self, name):
        return face(surface="plane", contains=V(*self.points()[name]))

    def check(self):
        box = self.pad.Shape.BoundBox
        assert abs(box.ZMin) < 1e-6 and abs(box.ZMax - 10) < 1e-6, box
        assert abs(box.YMin + 5) < 1e-6 and abs(box.YMax - 5) < 1e-6, box

    def placeSketches(self, doc, turned):
        motion = FLIP_X if turned else App.Placement()
        self.base.Placement = motion
        self.axis.Placement = motion.multiply(App.Placement(V(0, 0, 0), App.Rotation(X, 90)))

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.MapMode = "Deactivated"
        pts = [V(-10, -5, 0), V(10, -5, 0), V(10, 5, 0), V(-10, 5, 0), V(-10, -5, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.axis = doc.addObject("Sketcher::SketchObject", "AxisSketch")
        body.addObject(self.axis)
        self.axis.MapMode = "Deactivated"
        self.axis.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 10, 0)), False)
        self.placeSketches(doc, False)
        doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.base
        pad.Length = 10
        pad.ReferenceAxis = (self.axis, ["Edge1"])
        doc.recompute()
        self.pad = pad
        assert pad.getEditorMode("Direction") == ["ReadOnly"], pad.getEditorMode("Direction")
        self.check()
        for name in self.REFS:
            element = self.names(pad, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(pad, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.placeSketches(doc, True)
        # In AxisSketch's turned frame, local (0, -10) is global (0, 0, 10)
        if self.redraw == "move":
            self.axis.moveGeometry(0, 2, V(0, -10, 0))
        else:
            self.axis.delGeometry(0)
            self.axis.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, -10, 0)), False)
        doc.recompute()
        self.check()


class RevPadAxisLineBothFlippedRigid(RevPadAxisLineRedrawnBothFlipped):
    """Control: the same turn with the axis line left as drawn (it turns with its sketch): the pad
    goes -z, z -10..0, the whole part turned by M. Convention: the references follow the part, the
    +y wall's reference lands on the wall now at y -5 (z -10..0)."""

    def points(self):
        return {"side_py": (0, -5, -5), "side_my": (0, 5, -5), "top": (0, 0, -10),
                "bottom": (0, 0, 0)}

    def build(self, doc):
        self.turned = False
        RevPadAxisLineRedrawnBothFlipped.build(self, doc)

    def expect(self, name):
        pts = self.points() if self.turned else RevPadAxisLineRedrawnBothFlipped.points(self)
        return face(surface="plane", contains=V(*pts[name]))

    def check(self):
        box = self.pad.Shape.BoundBox
        z0, z1 = (-10, 0) if getattr(self, "turned", False) else (0, 10)
        assert abs(box.ZMin - z0) < 1e-6 and abs(box.ZMax - z1) < 1e-6, box

    def edit(self, doc):
        self.turned = True
        self.placeSketches(doc, True)
        doc.recompute()
        self.check()


class RevPadAxisLineRedrawnBaseFlippedOnly(RevPadAxisLineRedrawnBothFlipped):
    """Control: only the profile sketch turned (AxisSketch stays, not redrawn): the sources don't
    move by one motion, so the rigid reading is off. Same solid, the references stay."""

    def edit(self, doc):
        self.base.Placement = FLIP_X
        doc.recompute()
        self.check()


class RevRevolveAxisLineRedrawnBothFlipped(Scenario):
    """A rectangle x 5..10, z -5..5 in an unattached sketch Profile lying in the XZ plane
    (Placement 90 about X), revolved 90 degrees about a REFERENCE AXIS: the line
    (0,0,-5)->(0,0,5) of a second unattached sketch AxisSketch with the same placement. The
    Revolution's Base/Axis are Prop_ReadOnly (left out of the record). The edit turns BOTH sketches
    by the same half turn M about the global X axis (the rectangle lands on itself, its top line at
    the bottom) and redraws the axis line's end point so that the line runs +z again globally
    ((0,0,5)->(0,0,15) in the turned frame's terms: local (0,-5)->(0,-15)): the revolve sweeps the
    same quarter as before, the same solid (the part did not move as one piece: M would have swept
    the other quarter, y < 0). Convention 10.1: every reference stays (the top face is the top
    face, the end face at angle 90 is still there)."""
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2c"
    TIER = "F"
    REFS = ("top", "bottom", "start", "end")
    feature = "PartDesign::Revolution"

    def points(self):
        c = 7.5 * 0.7071067811865476
        return {"top": (c, c, 5), "bottom": (c, c, -5), "start": (7.5, 0, 0), "end": (0, 7.5, 0)}

    def expect(self, name):
        return face(surface="plane", contains=V(*self.points()[name]))

    def check(self):
        box = self.rev.Shape.BoundBox
        assert abs(box.ZMin + 5) < 1e-6 and abs(box.ZMax - 5) < 1e-6, box
        assert abs(box.XMin) < 1e-6 and abs(box.XMax - 10) < 1e-6, box
        assert abs(box.YMin) < 1e-6 and abs(box.YMax - 10) < 1e-6, box

    def placeSketches(self, turned):
        motion = FLIP_X if turned else App.Placement()
        frame = motion.multiply(App.Placement(V(0, 0, 0), App.Rotation(X, 90)))
        self.profile.Placement = frame
        self.axis.Placement = frame

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.profile = doc.addObject("Sketcher::SketchObject", "Profile")
        body.addObject(self.profile)
        self.profile.MapMode = "Deactivated"
        pts = [V(5, -5, 0), V(10, -5, 0), V(10, 5, 0), V(5, 5, 0), V(5, -5, 0)]
        for i in range(4):
            self.profile.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.axis = doc.addObject("Sketcher::SketchObject", "AxisSketch")
        body.addObject(self.axis)
        self.axis.MapMode = "Deactivated"
        self.axis.addGeometry(Part.LineSegment(V(0, -5, 0), V(0, 5, 0)), False)
        self.placeSketches(False)
        doc.recompute()
        rev = body.newObject(self.feature, "Rev")
        rev.Profile = self.profile
        rev.ReferenceAxis = (self.axis, ["Edge1"])
        rev.Angle = 90
        doc.recompute()
        self.rev = rev
        if self.rev.Shape.BoundBox.YMin < -1:
            rev.Reversed = True
            doc.recompute()
        self.check()
        for name in self.REFS:
            element = self.names(rev, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(rev, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.placeSketches(True)
        self.axis.moveGeometry(0, 2, V(0, -15, 0))
        doc.recompute()
        self.check()


class RevRevolveAxisLineBothFlippedRigid(RevRevolveAxisLineRedrawnBothFlipped):
    """Control: the same turn, the axis line left as drawn: the revolve sweeps the y < 0 quarter,
    M of the old solid (top and bottom traded, the end face at angle -90). The references follow
    the part."""

    def build(self, doc):
        self.turned = False
        RevRevolveAxisLineRedrawnBothFlipped.build(self, doc)

    def expect(self, name):
        c = 7.5 * 0.7071067811865476
        pts = RevRevolveAxisLineRedrawnBothFlipped.points(self)
        if self.turned:
            pts = {"top": (c, -c, -5), "bottom": (c, -c, 5), "start": (7.5, 0, 0),
                   "end": (0, -7.5, 0)}
        return face(surface="plane", contains=V(*pts[name]))

    def check(self):
        box = self.rev.Shape.BoundBox
        if getattr(self, "turned", False):
            assert abs(box.YMin + 10) < 1e-6 and abs(box.YMax) < 1e-6, box
        else:
            RevRevolveAxisLineRedrawnBothFlipped.check(self)

    def edit(self, doc):
        self.turned = True
        self.placeSketches(True)
        doc.recompute()
        self.check()


class RevRevolveAxisLineRedrawnBothFlippedAttached(RevRevolveAxisLineRedrawnBothFlipped):
    """The same with both sketches attached FlatFace to the Body's XZ plane, the motion made by
    their AttachmentOffsets (offset = plane^-1 * the placement above)."""

    def placeSketches(self, turned):
        motion = FLIP_X if turned else App.Placement()
        frame = motion.multiply(App.Placement(V(0, 0, 0), App.Rotation(X, 90)))
        body = self.profile.getParentGeoFeatureGroup()
        plane = originFeature(body, "XZ_Plane")
        for sketch in (self.profile, self.axis):
            if sketch.MapMode != "FlatFace":
                sketch.AttachmentSupport = [(plane, "")]
                sketch.MapMode = "FlatFace"
            sketch.AttachmentOffset = plane.Placement.inverse().multiply(frame)


class RevRevolveAxisLineBothFlippedRigidAttached(RevRevolveAxisLineBothFlippedRigid):
    """Control for the attached route."""

    placeSketches = RevRevolveAxisLineRedrawnBothFlippedAttached.placeSketches


class RevPadAxisLineRedrawnBothFlippedAttached(RevPadAxisLineRedrawnBothFlipped):
    """The Pad case with both sketches attached FlatFace (Base to XY, AxisSketch to XZ), the motion
    made by their AttachmentOffsets."""

    def placeSketches(self, doc, turned):
        motion = FLIP_X if turned else App.Placement()
        body = self.base.getParentGeoFeatureGroup()
        frames = ((self.base, "XY_Plane", motion),
                  (self.axis, "XZ_Plane",
                   motion.multiply(App.Placement(V(0, 0, 0), App.Rotation(X, 90)))))
        for sketch, role, frame in frames:
            plane = originFeature(body, role)
            if sketch.MapMode != "FlatFace":
                sketch.AttachmentSupport = [(plane, "")]
                sketch.MapMode = "FlatFace"
            sketch.AttachmentOffset = plane.Placement.inverse().multiply(frame)


class RevRevolveOwnAxisLineRedrawnFlipped(RevRevolveAxisLineRedrawnBothFlippedAttached):
    """The common form: the axis is a construction line in the profile sketch itself
    (ReferenceAxis Axis0), the sketch attached FlatFace to the XZ plane. The edit turns the sketch
    by M (half turn about the global X axis, its AttachmentOffset) and drags the axis line's end
    point so that it runs +z again: the same quarter, the same solid. One placement source, moved
    by M; the Revolution's Base/Axis are left out of the record."""

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        self.profile = doc.addObject("Sketcher::SketchObject", "Profile")
        body.addObject(self.profile)
        pts = [V(5, -5, 0), V(10, -5, 0), V(10, 5, 0), V(5, 5, 0), V(5, -5, 0)]
        for i in range(4):
            self.profile.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.lineId = self.profile.addGeometry(Part.LineSegment(V(0, -5, 0), V(0, 5, 0)), True)
        self.axis = self.profile
        self.placeSketches(False)
        doc.recompute()
        rev = body.newObject(self.feature, "Rev")
        rev.Profile = self.profile
        rev.ReferenceAxis = (self.profile, ["Axis0"])
        rev.Angle = 90
        doc.recompute()
        self.rev = rev
        if self.rev.Shape.BoundBox.YMin < -1:
            rev.Reversed = True
            doc.recompute()
        self.check()
        for name in self.REFS:
            element = self.names(rev, self.expect(name))[0]
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(rev, element)]
            owner.MapMode = "FlatFace"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), Attached())

    def edit(self, doc):
        self.placeSketches(True)
        self.profile.moveGeometry(self.lineId, 2, V(0, -15, 0))
        doc.recompute()
        self.check()
