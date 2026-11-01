# SPDX-License-Identifier: LGPL-2.1-or-later
"""Class D cases of the rigid turn (PLAN decision 212; `notes\\naming-class-D.md` section 11): a
part moved as one piece, every placement source of its chain by the same rigid motion, with
references that must follow it.

The box of `corpus\\inbox\\D\\ops557\\frame_turn.py`: a Pad 20 x 10 x 10 at the origin with two
holes of radius 1.5 at (5, 5) and (15, 5) through its top face (the holes' sketch attached to the
Pad, ObjectXY, so it moves with the part). Here its base sketch sits on the Body's XY plane with
an AttachmentOffset, the common way a sketch is positioned, so the chain's frame (the first
feature's Placement, `positionByPrevious`: the support's placement) is the identity and does not
move when the offset turns: the part turns inside its frame. Expected results follow decision 212:
the references follow the part. The references are those of `frame_turn.py`'s box
(`hole1_rim`, `hole1_wall`, `top`, `end_x0`, `edge_y0`, `corner_000`, `corner_top`), on the Pocket
or on the Body.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex

V = App.Vector
Z = V(0, 0, 1)
IDENTITY = App.Placement()


class RigidBox(Scenario):
    """The box, one edit (`motion`, the global motion of the part), and references into the
    last feature (or the Body: `held` "body"). Each reference is an element's kind and a point
    on it before the edit; the expectation moves the point with the part (`follow` True)."""

    abstract = True
    area = "rigid"
    CLASSES = ("D",)
    ISSUE = "ops#557"
    FOUND_BY = "designer rigid turns"
    TIER = "F"
    motion = IDENTITY
    follow = True
    STAY = ()  # references whose element does not move with the part (a tool left behind)
    held = "feature"  # or "body": the references held on the Body
    baseOn = "offset"  # "offset": the base sketch on XY_Plane with an AttachmentOffset; "placement"
    # where the holes' sketch is attached: "block" (ObjectXY on the Pad: its Placement, which is
    # the support's when the base sketch is attached), "base" (ObjectXY on the base sketch),
    # "face" (FlatFace on the Pad's top face)
    holesOn = "block"
    REFS = ("hole1_rim", "hole1_wall", "top", "end_x0", "edge_y0", "corner_000", "corner_top")
    ELEMENTS = {
        "hole1_rim": ("arc", (6.5, 5, 10)),
        "hole1_wall": ("cylinder", (6.5, 5, 5)),
        "top": ("plane", (10, 1, 10)),
        "end_x0": ("plane", (0, 5, 5)),
        "edge_y0": ("line", (10, 0, 10)),
        "corner_000": ("vertex", (0, 0, 0)),
        "corner_top": ("vertex", (0, 0, 10)),
    }

    def where(self, pt, name=None):
        if name in self.STAY:
            return V(*pt)
        return self.motion.multVec(V(*pt)) if (self.follow and self.stepName) else V(*pt)

    def expect(self, name):
        spec = self.ELEMENTS[name]
        return self.expectAt(spec[0], self.where(spec[1], name))

    def expectAt(self, kind, pt):
        if kind == "arc":
            return edge(curve="circle", contains=pt)
        if kind == "line":
            return edge(curve="line", contains=pt)
        if kind == "plane":
            return face(surface="plane", contains=pt)
        if kind == "cylinder":
            return face(surface="cylinder", contains=pt)
        return vertex(pt)

    def consumer(self, doc, body, name, target):
        """A datum point at the element, or a sketch on a plane face. Held on the Body: a sketch
        outside the body for a face, a Part::Vertex-free datum through a document-level sketch
        for the rest (attached to the Body's element)."""
        kind = self.ELEMENTS[name][0]
        element = self.names(target, self.expect(name))[0]
        if self.held == "body":
            owner = doc.addObject("Sketcher::SketchObject", name)
            owner.AttachmentSupport = [(target, element)]
            if kind == "plane":
                owner.MapMode = "FlatFace"
            elif kind == "vertex":
                owner.MapMode = "Translate"
            elif kind == "line":
                owner.MapMode = "NormalToEdge"
            else:
                owner.MapMode = "Concentric" if kind == "arc" else "Translate"
            return owner, Attached()
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

    def model(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        if self.baseOn == "offset":
            xy = [f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)][0]
            self.base.AttachmentSupport = [(xy, "")]
            self.base.MapMode = "FlatFace"
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.addGeometry(Part.Circle(V(5, 5, 0), Z, 1.5), False)
        self.holes.addGeometry(Part.Circle(V(15, 5, 0), Z, 1.5), False)
        if self.holesOn == "face":
            top = self.names(self.block, face(surface="plane", contains=V(10, 1, 10)))[0]
            self.holes.AttachmentSupport = [(self.block, top)]
            self.holes.MapMode = "FlatFace"
        else:
            self.holes.AttachmentSupport = [(self.base if self.holesOn == "base" else self.block, "")]
            self.holes.MapMode = "ObjectXY"
            self.holes.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holes
        self.pocket.Type = 1
        return self.pocket

    def build(self, doc):
        self.body = doc.addObject("PartDesign::Body", "Body")
        last = self.model(doc, self.body)
        doc.recompute()
        target = self.body if self.held == "body" else last
        for name in self.REFS:
            owner, outcome = self.consumer(doc, self.body, name, target)
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), outcome)

    def move(self, doc):
        if self.baseOn == "offset":
            self.base.AttachmentOffset = self.motion
        else:
            self.base.Placement = self.motion

    def edit(self, doc):
        self.move(doc)


class RigidBoxTurnedAboutCentreOffset(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset turns 180 degrees about the box's centre (onto itself): the frame stays, the part turns in it. The holes' sketch is attached to the Pad's Placement, which is the plane's: the holes stay (the tool left behind), the box turns under them."
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    STAY = ("hole1_rim", "hole1_wall")


class RigidBoxTurnedAboutCentreOffsetHolesOnBase(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset turns 180 degrees about the box's centre; the holes' sketch is attached ObjectXY to the base sketch, so it turns with the part."
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    holesOn = "base"


class RigidBoxTurnedAboutCentreOffsetHolesOnFace(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset turns 180 degrees about the box's centre; the holes' sketch is attached FlatFace to the Pad's top face, whose plane is canonical (the face maker's), so the sketch stays: FreeCAD leaves a face-attached tool behind, and the part is not turned as one piece."
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    holesOn = "face"
    STAY = ("hole1_rim", "hole1_wall")


class RigidBoxMovedTurnedOffset(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset moves the box to (3, 4) and turns it 30 degrees; the holes' sketch on the base sketch: no element where another was (control)."
    motion = App.Placement(V(3, 4, 0), App.Rotation(Z, 30))
    holesOn = "base"


class RigidBoxShiftedByPitchOffset(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset shifts the box by the holes' pitch along -x; the holes' sketch on the base sketch: hole 2 where hole 1 was."
    motion = App.Placement(V(-10, 0, 0), App.Rotation())
    holesOn = "base"


class RigidBoxTurnedAboutCentreBodyHeld(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's Placement turns 180 degrees about the box's centre; the references are held on the Body (body coordinates: the tip's placement baked in)."
    baseOn = "placement"
    held = "body"
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    REFS = tuple(r for r in RigidBox.REFS if r != "hole1_wall")  # no attach mode takes a cylinder


class RigidBoxTurnedAboutCentreOffsetBodyHeld(RigidBoxTurnedAboutCentreBodyHeld):
    __doc__ = RigidBox.__doc__ + " The base sketch's AttachmentOffset turns 180 degrees about the box's centre; the references are held on the Body. The holes' sketch (ObjectXY on the Pad, whose Placement is the plane's) stays."
    baseOn = "offset"
    STAY = ("hole1_rim",)


class RigidBoxTurnedAndHoleWidened(RigidBox):
    __doc__ = RigidBox.__doc__ + " The base sketch's Placement turns 180 degrees about the box's centre and hole 1 widens from 1.5 to 2 in the same recompute: a rigid turn with an edit."
    baseOn = "placement"
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    WIDENED = {"hole1_rim": ("arc", (7, 5, 10)), "hole1_wall": ("cylinder", (7, 5, 5))}

    def expect(self, name):
        if self.stepName and name in self.WIDENED:
            kind, pt = self.WIDENED[name]
            return self.expectAt(kind, self.where(pt, name))
        return RigidBox.expect(self, name)

    def move(self, doc):
        RigidBox.move(self, doc)
        g = self.holes.Geometry
        g[0].Radius = 2.0
        self.holes.Geometry = g


class RigidBoxMixedTools(RigidBox):
    __doc__ = RigidBox.__doc__ + " A second Pocket of a 2 x 2 square at (18, 5), its sketch fixed in the body (not attached); the base sketch's Placement turns 180 degrees about the centre: the holes follow, the square stays. Not a rigid turn of the closure (control: today's rules, decision 211)."
    baseOn = "placement"
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    REFS = RigidBox.REFS + ("square_px",)
    ELEMENTS = dict(RigidBox.ELEMENTS, square_px=("plane", (19, 5, 5)))

    STAY = ("square_px",)  # the fixed tool stays

    def model(self, doc, body):
        RigidBox.model(self, doc, body)
        self.square = doc.addObject("Sketcher::SketchObject", "Square")
        body.addObject(self.square)
        a = 1.0
        c = V(18, 5, 0)
        pts = [c + V(-a, -a, 0), c + V(a, -a, 0), c + V(a, a, 0), c + V(-a, a, 0), c + V(-a, -a, 0)]
        for i in range(4):
            self.square.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.square.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        self.notch = body.newObject("PartDesign::Pocket", "Notch")
        self.notch.Profile = self.square
        self.notch.Type = 1
        return self.notch
