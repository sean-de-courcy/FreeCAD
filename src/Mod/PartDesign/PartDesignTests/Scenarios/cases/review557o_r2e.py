# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr557o-r2e (fork PR 557o round 2e, decision 234's two-place read): attacks on the
followed (M_local) reading where it differs from the stored record, the offset route (a sketch on
an origin plane turned by its AttachmentOffset: the chain's frame stays) and Body-held records,
and on a broken reference's stale record healed by a later edit. Designed geometry only; the
expectation follows the part where it moved as one piece (decision 212) and the history of the
edited element (the circle that moved is the hole that moved)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, X, Y, Z, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
IDENTITY = App.Placement()


def originFeature(body, role):
    return [f for f in body.Origin.OriginFeatures if role in (getattr(f, "Role", ""), f.Name)][0]


# ---- the box of rigid_turn.py (copied: this module also runs on integration)


class Box(Scenario):
    """A Pad 20 x 10 x 10 (base sketch on XY_Plane, FlatFace, moved by its AttachmentOffset: the
    offset route), two holes of radius 1.5 at local (5, 5) and (15, 5) from a sketch attached
    ObjectXY to the base sketch (it moves with the part). `motion` is the part's global motion;
    `edited` the other edit of the same recompute."""

    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2e"
    TIER = "F"
    motion = IDENTITY
    held = "feature"
    baseOn = "offset"
    REFS = ("hole1_rim", "hole1_wall", "hole2_rim", "end_x0", "corner_000")
    ELEMENTS = {
        "hole1_rim": ("arc", (6.5, 5, 10)),
        "hole1_wall": ("cylinder", (6.5, 5, 5)),
        "hole2_rim": ("arc", (16.5, 5, 10)),
        "top": ("plane", (10, 1, 10)),
        "end_x0": ("plane", (0, 5, 5)),
        "edge_y0": ("line", (10, 0, 10)),
        "corner_000": ("vertex", (0, 0, 0)),
    }
    AFTER = {}  # local points after the edit, where the edit moved the element in the part

    def where(self, name):
        pt = self.ELEMENTS[name][1]
        if self.stepName and name in self.AFTER:
            pt = self.AFTER[name]
        return self.motion.multVec(V(*pt)) if self.stepName else V(*pt)

    def expect(self, name):
        if self.stepName and self.AFTER.get(name) == "broken":
            return BROKEN
        return self.expectAt(self.ELEMENTS[name][0], self.where(name))

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
        kind = self.ELEMENTS[name][0]
        element = self.names(target, self.expectAt(kind, V(*self.ELEMENTS[name][1])))[0]
        if self.held == "body":
            owner = doc.addObject("Sketcher::SketchObject", name)
            owner.AttachmentSupport = [(target, element)]
            owner.MapMode = {"plane": "FlatFace", "vertex": "Translate", "line": "NormalToEdge",
                             "arc": "Concentric"}.get(kind, "Translate")
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
            self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
            self.base.MapMode = "FlatFace"
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.addGeometry(Part.Circle(V(5, 5, 0), Z, 1.5), False)
        self.holes.addGeometry(Part.Circle(V(15, 5, 0), Z, 1.5), False)
        self.holes.AttachmentSupport = [(self.base, "")]
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

    def move(self):
        if self.baseOn == "offset":
            self.base.AttachmentOffset = self.motion
        else:
            self.base.Placement = self.motion

    def edited(self, doc):
        pass

    def edit(self, doc):
        self.move()
        self.edited(doc)
        doc.recompute()


SWAPPED = {"hole1_rim": (16.5, 5, 10), "hole1_wall": (16.5, 5, 5), "hole2_rim": (6.5, 5, 10)}


class Rv2eHolesSwappedMovedOff(Box):
    """The part moves off its old place (+30 in y, offset route) and the two circles swap places in
    the same recompute (circle 0 to x 15, circle 1 to x 5): one piece with another edit, the old
    places empty (rule (1)). Each hole follows its circle; FOLLOWED for hole 1 holds hole 2."""

    motion = App.Placement(V(0, 30, 0), App.Rotation())
    AFTER = SWAPPED

    def edited(self, doc):
        g = self.holes.Geometry
        g[0].Center = V(15, 5, 0)
        g[1].Center = V(5, 5, 0)
        self.holes.Geometry = g


class Rv2eHolesSwappedMovedOffBodyHeld(Rv2eHolesSwappedMovedOff):
    """As Rv2eHolesSwappedMovedOff, the references held on the Body."""

    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "end_x0", "corner_000")


class Rv2eHolesSwappedMovedOffPlacement(Rv2eHolesSwappedMovedOff):
    """As Rv2eHolesSwappedMovedOff, the base sketch unattached, moved by its Placement (the frame
    moves with the part)."""

    baseOn = "placement"


class Rv2eHolesSwappedTurned(Rv2eHolesSwappedMovedOff):
    """The part turned 180 about its centre onto itself (offset route) and the circles swapped in
    the same recompute: globally each circle's hole is back at its old place."""

    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))


class Rv2eHole2DeletedHole1SlidMovedOff(Box):
    """The part moves off (+30 in y, offset route) and in the same recompute circle 1 is deleted and
    circle 0 slides to x 15 (where circle 1 was): hole 2 is gone (broken is the only right
    answer); hole 1 follows its circle. FOLLOWED for hole 2 holds hole 1, an older source."""

    motion = App.Placement(V(0, 30, 0), App.Rotation())
    REFS = ("hole1_rim", "hole1_wall", "hole2_rim", "corner_000")
    AFTER = {"hole1_rim": (16.5, 5, 10), "hole1_wall": (16.5, 5, 5), "hole2_rim": "broken"}

    def edited(self, doc):
        g = self.holes.Geometry
        g[0].Center = V(15, 5, 0)
        self.holes.Geometry = g
        self.holes.delGeometry(1)


class Rv2eHole2DeletedHole1SlidMovedOffBodyHeld(Rv2eHole2DeletedHole1SlidMovedOff):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "corner_000")


class Rv2eWidenedMovedOffBodyHeld(Box):
    """The part moves and turns 30 degrees off its old place (offset route), hole 1 widened to
    radius 2 in the same recompute; the references held on the Body (rule (1) on M)."""

    held = "body"
    motion = App.Placement(V(3, 4, 0), App.Rotation(Z, 30))
    REFS = ("hole1_rim", "hole2_rim", "end_x0", "corner_000", "top")
    AFTER = {"hole1_rim": (7, 5, 10)}

    def edited(self, doc):
        g = self.holes.Geometry
        g[0].Radius = 2.0
        self.holes.Geometry = g


class Rv2eWidenedTurnedBodyHeld(Rv2eWidenedMovedOffBodyHeld):
    """The part turned 180 about its centre onto itself (base sketch's Placement), hole 1 widened in
    the same recompute; the references held on the Body (Body-held: T = I, OLD the record)."""

    baseOn = "placement"
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))


class Rv2eWidenedTurnedOffset(Rv2eWidenedTurnedBodyHeld):
    """As Rv2eWidenedTurnedBodyHeld, offset route, references on the Pocket."""

    held = "feature"
    baseOn = "offset"
    REFS = ("hole1_rim", "hole1_wall", "hole2_rim", "end_x0", "corner_000", "top", "edge_y0")
    AFTER = {"hole1_rim": (7, 5, 10), "hole1_wall": (7, 5, 5)}


class Rv2eSlidAlongEdgeLengthened(Box):
    """The part shifts +5 along x (offset route; FOLLOWED overlaps OLD on the same carrier for the
    y = 0 top edge and the top face) and the pad gets 2 longer in the same recompute: every
    reference follows."""

    motion = App.Placement(V(5, 0, 0), App.Rotation())
    REFS = ("edge_y0", "top", "end_x0", "corner_000")
    AFTER = {"edge_y0": (10, 0, 12), "top": (10, 1, 12)}

    def edited(self, doc):
        self.block.Length = 12


# ---- the pattern of rigid_attack.py's R2dPattern (copied), moved off instead of turned

class Rv2ePatternSpacingsMovedOff(Scenario):
    """A box x 0..40, y 0..10, z 0..10 (base sketch on XY_Plane, AttachmentOffset), a hole r 1.5 at
    local (8, 5) from a sketch ObjectXY on the base, LinearPattern along the sketch's H axis
    (Spacing mode, 8, 4 occurrences): holes at x 8, 16, 24, 32. The edit moves the part +30 in y
    and sets Spacings [4, 4, 8] in the same recompute: instance k at local x 8, 12, 16, 24.
    Instance 1's FOLLOWED place (local 16) holds instance 2."""

    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2e"
    TIER = "F"
    REFS = ("rim1", "rim2", "rim3")
    LOCAL = {"rim1": 1, "rim2": 2, "rim3": 3}
    motion = App.Placement(V(0, 30, 0), App.Rotation())
    spacings = [4.0, 4.0, 8.0]
    held = "feature"

    def localX(self, k):
        steps = [8.0] * 3
        if self.stepName:
            steps = list(self.spacings)
        return 8.0 + sum(steps[:k])

    def expect(self, name):
        k = self.LOCAL[name]
        p = V(self.localX(k), 6.5, 10)
        if self.stepName:
            p = self.motion.multVec(p)
        return edge(curve="circle", contains=p)

    def build(self, doc):
        self.body = body = doc.addObject("PartDesign::Body", "Body")
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        self.base.AttachmentSupport = [(originFeature(body, "XY_Plane"), "")]
        self.base.MapMode = "FlatFace"
        pts = [V(0, 0, 0), V(40, 0, 0), V(40, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.addGeometry(Part.Circle(V(8, 5, 0), Z, 1.5), False)
        self.holes.addGeometry(Part.LineSegment(V(0, 5, 0), V(1, 5, 0)), True)
        self.holes.AttachmentSupport = [(self.base, "")]
        self.holes.MapMode = "ObjectXY"
        self.holes.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holes
        self.pocket.Type = 1
        doc.recompute()
        self.pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        self.pattern.Originals = [self.pocket]
        self.pattern.Direction = (self.holes, ["H_Axis"])
        self.pattern.Mode = "Spacing"
        self.pattern.Offset = 8
        self.pattern.Occurrences = 4
        body.Tip = self.pattern
        doc.recompute()
        assert self.pattern.isValid(), self.pattern.getStatusString()
        target = body if self.held == "body" else self.pattern
        for name in self.REFS:
            element = self.names(target, self.expect(name))[0]
            if self.held == "body":
                owner = doc.addObject("Sketcher::SketchObject", name)
                owner.AttachmentSupport = [(target, element)]
                owner.MapMode = "Concentric"
            else:
                owner = body.newObject("PartDesign::Point", name)
                owner.AttachmentSupport = [(target, element)]
                owner.MapMode = "CenterOfMass"
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), None)

    def edit(self, doc):
        self.base.AttachmentOffset = self.motion
        self.pattern.Spacings = list(self.spacings)
        doc.recompute()
        assert self.pattern.isValid(), self.pattern.getStatusString()


class Rv2ePatternSpacingsMovedOffBodyHeld(Rv2ePatternSpacingsMovedOff):
    held = "body"


class Rv2ePatternShiftedByStepSpacings(Rv2ePatternSpacingsMovedOff):
    """The part shifts -8 in x (one pattern step, offset route) and Spacings become [16, 8, 4] in the
    same recompute: instances at local 8, 24, 32, 36 (global 0, 16, 24, 28). Instance 1 and 2 are
    back at their old global places (OLD holds the hit), their FOLLOWED places (global 8, 16) hold
    nothing / instance 1."""

    motion = App.Placement(V(-8, 0, 0), App.Rotation())
    spacings = [16.0, 8.0, 4.0]
    REFS = ("rim1", "rim2")


# ---- the ring of pipe_closed_r6l.py (copied), offset route and Body-held


class Ring(Scenario):
    abstract = True
    area = "rigid-review"
    CLASSES = ("B",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2e"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    half = 2
    verts0 = ((0, 0), (0, 20), (30, 20), (30, 0))
    pivot = (15, 0, 10)
    axis = Y
    degrees = 0
    lift = (0, 0, 0)
    verts = None
    route = "offset"  # or "placement"
    held = "feature"  # or "body"
    REFS = ("leg0", "leg1", "leg2", "leg3", "start_pt")

    A = property(lambda self: self.s(self.half))

    def P(self):
        if self.verts is None:
            self.verts = [tuple(self.s(c) for c in p) for p in self.verts0]
        return self.verts

    def T(self):
        rot = App.Rotation(self.axis, self.degrees)
        c = V(*(self.s(v) for v in self.pivot))
        lift = V(*(self.s(v) for v in self.lift))
        return App.Placement(c - rot.multVec(c) + lift, rot)

    def at(self, x, y, z):
        return self.T().multVec(V(x, y, z))

    def along(self, d):
        return self.T().Rotation.multVec(d)

    def legFace(self, i):
        def predicate():
            P = self.P()
            n = len(P)
            (x0, z0), (x1, z1) = P[i % n], P[(i + 1) % n]
            dx, dz = x1 - x0, z1 - z0
            L = math.hypot(dx, dz)
            nx, nz = -dz / L, dx / L
            mx, mz = (x0 + x1) / 2 + nx * self.A, (z0 + z1) / 2 + nz * self.A
            return face("plane", normal=self.along(V(nx, 0, nz)), contains=self.at(mx, 0, mz))

        return predicate

    def startPoint(self):
        a = self.A
        return vertex(self.at(-a, -a, -a))

    def spinePlacement(self):
        return self.T().multiply(App.Placement(V(), App.Rotation(X, 90)))

    def profilePlacement(self):
        return self.T()

    def place(self):
        if self.route == "offset":
            self.spine.AttachmentOffset = self.xz.Placement.inverse().multiply(self.spinePlacement())
            self.profile.AttachmentOffset = self.xy.Placement.inverse().multiply(self.profilePlacement())
        else:
            self.spine.Placement = self.spinePlacement()
            self.profile.Placement = self.profilePlacement()

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.xz = originFeature(body, "XZ_Plane")
        self.xy = originFeature(body, "XY_Plane")
        P = self.P()
        self.spine = m.sketch(doc, "Spine", m.polygon(P), body)
        a = self.A
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), body)
        if self.route == "offset":
            self.spine.AttachmentSupport = [(self.xz, "")]
            self.spine.MapMode = "FlatFace"
            self.profile.AttachmentSupport = [(self.xy, "")]
            self.profile.MapMode = "FlatFace"
        self.place()
        doc.recompute()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        self.pipe = pipe
        target = body if self.held == "body" else pipe
        made = {}
        n = len(P)
        for name in self.REFS:
            if name.startswith("leg"):
                i = int(name[3:])
                if i >= n:
                    continue
                predicate = self.legFace(i)
                if self.held == "body":
                    obj = doc.addObject("Sketcher::SketchObject", name)
                else:
                    obj = body.newObject("PartDesign::Plane", name)
                obj.MapMode = "FlatFace"
            else:
                predicate = self.startPoint
                if self.held == "body":
                    obj = doc.addObject("Sketcher::SketchObject", name)
                    obj.MapMode = "Translate"
                else:
                    obj = body.newObject("PartDesign::Point", name)
                    obj.MapMode = "Vertex"
            obj.AttachmentSupport = [(target, self.names(target, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def redrawAll(self):
        P = self.P()
        n = len(P)
        g = self.spine.Geometry
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
        self.spine.Geometry = g

    def assign(self, verts0):
        self.verts = None
        self.verts0 = verts0
        P = self.P()
        n = len(P)
        g = self.spine.Geometry
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
        self.spine.Geometry = g


class Rv2eRingTurnedAllRedrawnBodyHeld(Ring):
    """The six silents' geometry (the 30 x 20 ring turned 180 about its normal through its centre,
    every line drawn anew in the same recompute), sketches moved by their Placements (the frame
    turns), references held on the Body (Body-held: OLD is the record)."""

    route = "placement"
    held = "body"

    def edit(self, doc):
        self.redrawAll()
        self.degrees = 180
        self.place()
        doc.recompute()


class Rv2eRingTurnedAllRedrawnOffsetBodyHeld(Rv2eRingTurnedAllRedrawnBodyHeld):
    route = "offset"


class Rv2eRingMovedAllRedrawnOffset(Ring):
    """Offset route: the whole ring moved off its old place (+40 in z, no turn), every line drawn
    anew in the same recompute (rule (1): nothing at OLD; the tiers on FOLLOWED)."""

    def edit(self, doc):
        self.redrawAll()
        self.lift = (0, 0, 40)
        self.place()
        doc.recompute()


class Rv2eRingMovedAllRedrawnOffsetBodyHeld(Rv2eRingMovedAllRedrawnOffset):
    held = "body"


class Rv2eSquareTurnedThenRaisedOffset(Ring):
    """Offset route, two steps: the 20 x 20 square ring turned 90 about its normal through its
    centre (on itself; rigid: the legs follow, the start breaks, ops#546), then its top leg raised
    to z 26 (lines 1 and 2 redrawn: the broken start's stale record is read against the turn and
    the raise)."""

    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)
    steps = ("doTurn", "doRaise")

    def doTurn(self, doc):
        self.degrees = 90
        self.place()
        doc.recompute()

    def doRaise(self, doc):
        self.assign(((0, 0), (0, 26), (20, 26), (20, 0)))
        doc.recompute()


class Rv2eSquareTurnedRedrawnThenRaisedOffset(Rv2eSquareTurnedThenRaisedOffset):
    """As above, the first step's turn made with every line drawn anew (it breaks), then the raise
    (the stale records of the broken references)."""

    def doTurn(self, doc):
        self.redrawAll()
        Rv2eSquareTurnedThenRaisedOffset.doTurn(self, doc)


class Rv2eRectTurnedRedrawnThenMovedOffOffset(Ring):
    """Offset route, two steps: the 30 x 20 ring turned 180 about its normal with every line drawn
    anew (breaks: the twin at OLD), then the whole turned model moved +40 in z (no OLD any more:
    the stale records read on FOLLOWED, rule (1))."""

    steps = ("doTurn", "doMove")

    def doTurn(self, doc):
        self.redrawAll()
        self.degrees = 180
        self.place()
        doc.recompute()

    def doMove(self, doc):
        self.lift = (0, 0, 40)
        self.place()
        doc.recompute()


class Rv2eRectTurnedRedrawnThenMovedOffPlacement(Rv2eRectTurnedRedrawnThenMovedOffOffset):
    route = "placement"


# ---- a key in one list only: the holes' tool fixed in the body, replaced in the same recompute


class Rv2eToolReplacedMovedOff(Box):
    """The holes' sketch Holes is fixed in the body (unattached, z 10: a tool that stays when the
    part moves). The edit moves the part +30 in y (offset route) and re-picks the Pocket's profile
    to a new sketch Holes2, unattached, whose circles sit at the old ones' places moved by the
    part's motion (x 5, 15; y 35): the old tool's key is in the saved list only, the new one's in
    the current list only, so the chain reads one piece with another edit. The holes the
    references named belonged to a sketch object that was replaced: policy D breaks them (decision
    20; I-S6 accepts a warned re-bind only at the identical place). The box's references follow."""

    motion = App.Placement(V(0, 30, 0), App.Rotation())
    REFS = ("hole1_rim", "hole1_wall", "hole2_rim", "end_x0", "corner_000")
    shift = V(0, 30, 0)  # where Holes2's circles sit, from the old ones
    HOLES = ("hole1_rim", "hole1_wall", "hole2_rim")

    def expect(self, name):
        # The old tool was fixed in the body: a replacement's hole re-binds only at the old hole's
        # place in the body (I-S6's accepted residual, LinkCopyReplacedSamePlace's convention),
        # else the reference breaks
        if self.stepName and name in self.HOLES:
            if not self.holeAtOld:
                return BROKEN
            kind, pt = self.ELEMENTS[name]
            return OwnOrBroken(self.expectAt(kind, V(*pt)))
        return Box.expect(self, name)

    holeAtOld = False  # a hole at the old hole's body place after the edit

    def model(self, doc, body):
        last = Box.model(self, doc, body)
        self.holes.AttachmentSupport = []
        self.holes.MapMode = "Deactivated"
        self.holes.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        return last

    def edited(self, doc):
        other = doc.addObject("Sketcher::SketchObject", "Holes2")
        self.body.addObject(other)
        other.addGeometry(Part.Circle(V(5, 5, 0) + self.shift, Z, 1.5), False)
        other.addGeometry(Part.Circle(V(15, 5, 0) + self.shift, Z, 1.5), False)
        other.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket.Profile = other
        self.holes.Visibility = False


class Rv2eToolReplacedInPlaceMovedOff(Rv2eToolReplacedMovedOff):
    """Control: Holes2's circles at the old ones' places (the tool stays where it was while the
    part moves off, the holes now cut where the part no longer is: x 5, 15; y 5 is outside the
    box at y 30..40, so the pocket cuts nothing there). The holes are gone: broken."""

    shift = V(0, 0, 0)


class Rv2eToolReplacedTurned(Rv2eToolReplacedMovedOff):
    """The part turned 180 about its centre onto itself (offset route) and the tool re-picked to
    Holes2 with its circles at the turned places (x 15, 5: the same two places): the model is the
    same solid. Policy D: the replaced sketch's holes break (or re-bind warned at the identical
    place)."""

    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
    shift = V(0, 0, 0)
    holeAtOld = True


class Rv2eToolReplacedNoMove(Rv2eToolReplacedMovedOff):
    """Control: no motion, the tool re-picked to Holes2 at the same places (I-S6's accepted warned
    re-bind at the identical place)."""

    motion = IDENTITY
    shift = V(0, 0, 0)
    holeAtOld = True


class Rv2eToolReplacedMovedOffBodyHeld(Rv2eToolReplacedMovedOff):
    """As Rv2eToolReplacedMovedOff, the references held on the Body."""

    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "end_x0", "corner_000")


class Rv2eToolReplacedMovedOffPlacement(Rv2eToolReplacedMovedOff):
    """As Rv2eToolReplacedMovedOff, the base sketch unattached and moved by its Placement (the
    Pocket's frame moves with the part: the stored record is the followed one on both builds)."""

    baseOn = "placement"


class Rv2eToolReplacedTurned90Off(Rv2eToolReplacedMovedOff):
    """As Rv2eToolReplacedMovedOff, the part turned 90 degrees about (0, 0) and moved +40 in x
    (off its old place), Holes2's circles at the old ones' places moved the same way."""

    motion = App.Placement(V(40, 0, 0), App.Rotation(Z, 90))

    def edited(self, doc):
        other = doc.addObject("Sketcher::SketchObject", "Holes2")
        self.body.addObject(other)
        for c in (V(5, 5, 0), V(15, 5, 0)):
            other.addGeometry(Part.Circle(self.motion.multVec(c), Z, 1.5), False)
        other.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket.Profile = other
        self.holes.Visibility = False


# ---- a vector input that drives nothing (a stale Binormal): the closure reads "not one piece"


class Rv2eRingStaleBinormalTurned(Ring):
    """The 30 x 20 ring and its profile turned 180 about the ring's normal through its centre (the
    whole model, sketches by their Placements: the frame turns), nothing else edited. The Pipe's
    Binormal is (0, 0, 1), set while its Mode is Standard: it drives nothing, but it is a vector
    input of the chain that does not turn with the part, so the closure is not one piece and
    decision 211 decides. Every reference follows the turn (RectTurned180AboutNormal's
    expectation)."""

    route = "placement"
    binormal = V(0, 0, 1)

    def build(self, doc):
        Ring.build(self, doc)
        self.pipe.Binormal = self.binormal
        doc.recompute()
        for obj in doc.Objects:
            pass

    def edit(self, doc):
        self.degrees = 180
        self.place()
        doc.recompute()


class Rv2eRingStaleBinormalTurnedOffset(Rv2eRingStaleBinormalTurned):
    route = "offset"


class Rv2eRingStaleBinormalTurnedBodyHeld(Rv2eRingStaleBinormalTurned):
    held = "body"


class Rv2eSquareStaleBinormalTurned90(Rv2eRingStaleBinormalTurned):
    """As Rv2eRingStaleBinormalTurned, the 20 x 20 square ring turned 90 about its normal."""

    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)

    def edit(self, doc):
        self.degrees = 90
        self.place()
        doc.recompute()


class Rv2eRingBinormalAlongAxisTurned(Rv2eRingStaleBinormalTurned):
    """Control: the stale Binormal (0, 1, 0), along the turn's axis: it turns with the part, the
    closure is one piece (rigid)."""

    binormal = V(0, 1, 0)
