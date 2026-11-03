# Review pr557s-r2e (decision 234): a plate turned as one piece with another edit, in the
# placement route (the chain's frame turns with the part), the offset route (the frame stays) and
# held on the Body.  A plate 20 x 10 x 10 (Pad Block, base sketch Base), holes of radius 1.5
# (Pocket, sketch Holes ObjectXY on Base: they ride with the part), a turn of 180 about the
# plate's centre (10, 5): the plate lands on itself.  Expectations follow decision 212 (a
# reference follows the part) and are OwnOrBroken where the redraw makes the owner of an element
# ambiguous: never the element that sits where it was, unless it is also where it went.

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    OwnOrBroken,
    Scenario,
    edge,
    face,
    vertex,
)

V = App.Vector
Z = V(0, 0, 1)
TURN = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
IDENTITY = App.Placement()


def originFeature(body, role):
    return [f for f in body.Origin.OriginFeatures if role in (getattr(f, "Role", ""), f.Name)][0]


class Plate(Scenario):
    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("E5",)
    ISSUE = "ops#557"
    FOUND_BY = "review pr557s-r2e"
    TIER = "F"
    baseOn = "placement"  # "offset": FlatFace on XY_Plane with an AttachmentOffset
    holesX = (5, 15)
    holeR = 1.5
    held = "feature"
    motion = TURN
    follow = True
    # kind, point before the edit
    ELEMENTS = {
        "hole1_rim": ("arc", (6.5, 5, 10)),
        "hole1_wall": ("cylinder", (6.5, 5, 5)),
        "hole2_rim": ("arc", (16.5, 5, 10)),
        "top": ("plane", (10, 1, 10)),
        "end_x0": ("plane", (0, 5, 5)),
        "edge_y0": ("line", (10, 0, 10)),
        "corner_000": ("vertex", (0, 0, 0)),
    }
    REFS = ("hole1_rim", "hole1_wall", "hole2_rim", "top", "end_x0", "edge_y0", "corner_000")
    ownOrBroken = False

    AFTER = {}

    def where(self, pt, name):
        if self.stepName and self.follow:
            return self.motion.multVec(V(*pt))
        return V(*pt)

    def predicate(self, name):
        kind, pt = self.ELEMENTS[name]
        if self.stepName and name in self.AFTER:
            pt = self.AFTER[name]
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

    def expect(self, name):
        found = self.predicate(name)
        return OwnOrBroken(found) if (self.ownOrBroken and self.stepName) else found

    def consumer(self, doc, body, name, target):
        kind = self.ELEMENTS[name][0]
        element = self.names(target, self.predicate(name))[0]
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

    def circles(self):
        return [Part.Circle(V(x, 5, 0), Z, self.holeR) for x in self.holesX]

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
        for c in self.circles():
            self.holes.addGeometry(c, False)
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

    def move(self, doc):
        if self.baseOn == "offset":
            self.base.AttachmentOffset = self.motion
        else:
            self.base.Placement = self.motion

    def other(self, doc):
        pass

    def edit(self, doc):
        self.move(doc)
        self.other(doc)
        doc.recompute()


class E2BoxHolesRedrawnSwapped(Plate):
    """The turn and both circles drawn anew in the other order (circle 0 at x 15, circle 1 at x 5
    in the sketch's own frame): globally the model is the turned model; no old hole name survives."""
    ownOrBroken = True

    def other(self, doc):
        self.holes.deleteAllGeometry()
        for x in reversed(self.holesX):
            self.holes.addGeometry(Part.Circle(V(x, 5, 0), Z, self.holeR), False)


class E3BoxHolesRedrawnSameOrder(Plate):
    ownOrBroken = True

    def other(self, doc):
        self.holes.deleteAllGeometry()
        for x in self.holesX:
            self.holes.addGeometry(Part.Circle(V(x, 5, 0), Z, self.holeR), False)


class E4BoxHolesRedrawnSwappedOffset(E2BoxHolesRedrawnSwapped):
    baseOn = "offset"


class E5BoxHolesRedrawnSwappedBodyHeld(E2BoxHolesRedrawnSwapped):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "top", "end_x0", "edge_y0", "corner_000")


class E6BoxHolesRedrawnSwappedBodyHeldOffset(E5BoxHolesRedrawnSwappedBodyHeld):
    baseOn = "offset"


class E7BoxBaseRedrawn(Plate):
    """The turn and the base sketch's four lines drawn anew (same coordinates, new ids): the
    walls and corners lose their names."""
    ownOrBroken = True

    def other(self, doc):
        self.base.deleteAllGeometry()
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)


class E8BoxBaseRedrawnRotatedOrder(E7BoxBaseRedrawn):
    """As E7 with the lines drawn from the opposite corner (ids rotated by two)."""

    def other(self, doc):
        self.base.deleteAllGeometry()
        pts = [V(20, 10, 0), V(0, 10, 0), V(0, 0, 0), V(20, 0, 0), V(20, 10, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)


class E9BoxBaseRedrawnRotatedOrderOffset(E8BoxBaseRedrawnRotatedOrder):
    baseOn = "offset"


class E10BoxBaseRedrawnRotatedOrderBodyHeldOffset(E8BoxBaseRedrawnRotatedOrder):
    baseOn = "offset"
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "top", "end_x0", "edge_y0", "corner_000")


class ThreeHoles(Plate):
    abstract = True
    holesX = (4, 10, 16)
    ELEMENTS = {
        "hole1_rim": ("arc", (5.5, 5, 10)),
        "hole2_rim": ("arc", (11.5, 5, 10)),
        "hole3_rim": ("arc", (17.5, 5, 10)),
        "top": ("plane", (10, 1, 10)),
        "end_x0": ("plane", (0, 5, 5)),
        "corner_000": ("vertex", (0, 0, 0)),
    }
    REFS = ("hole1_rim", "hole2_rim", "hole3_rim", "top", "end_x0", "corner_000")


class E11ThreeHolesTurnedWidenedMiddle(ThreeHoles):
    """The turn and the middle hole (on the turn's axis) widened: hole 2 stays on itself."""

    AFTER = {"hole2_rim": (12, 5, 10)}

    def other(self, doc):
        g = self.holes.Geometry
        g[1].Radius = 2.0
        self.holes.Geometry = g


class E12ThreeHolesTurnedMiddleRedrawn(ThreeHoles):
    """The turn and the middle hole drawn anew (a new id, the same place): hole 2's face names go."""
    ownOrBroken = True

    def other(self, doc):
        self.holes.delGeometry(1)
        self.holes.addGeometry(Part.Circle(V(10, 5, 0), Z, self.holeR), False)


class E13ThreeHolesTurnedMiddleRedrawnOffset(E12ThreeHolesTurnedMiddleRedrawn):
    baseOn = "offset"


class E14ThreeHolesTurnedMiddleRedrawnBodyHeld(E12ThreeHolesTurnedMiddleRedrawn):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "hole3_rim", "top", "end_x0", "corner_000")


class E15ThreeHolesTurnedEndsSwapRedrawn(ThreeHoles):
    """The turn and the end holes' circles redrawn crossed (circle 0 at 16, circle 2 at 4 in the
    sketch frame: the turned model, the old names trade between the twins)."""
    ownOrBroken = True

    def other(self, doc):
        self.holes.delGeometry(2)
        self.holes.delGeometry(0)
        self.holes.addGeometry(Part.Circle(V(16, 5, 0), Z, self.holeR), False)
        self.holes.addGeometry(Part.Circle(V(4, 5, 0), Z, self.holeR), False)


class TwoStep(Plate):
    """Two steps with hole 1 wider (2.0) in the first.  `turnedIn` and `radiusIn` say, per step,
    whether the part is turned and hole 1's radius."""
    abstract = True
    ownOrBroken = True
    turnedIn = {}
    radiusIn = {}

    def predicate(self, name):
        kind, pt = self.ELEMENTS[name]
        x, y, z = pt
        radius = self.radiusIn.get(self.stepName, 1.5)
        if name in ("hole1_rim", "hole1_wall"):
            x = 5 + radius
        p = V(x, y, z)
        if self.turnedIn.get(self.stepName, False):
            p = self.motion.multVec(p)
        if kind == "arc":
            return edge(curve="circle", contains=p)
        if kind == "line":
            return edge(curve="line", contains=p)
        if kind == "plane":
            return face(surface="plane", contains=p)
        if kind == "cylinder":
            return face(surface="cylinder", contains=p)
        return vertex(p)

    def setRadius(self, doc, radius):
        g = self.holes.Geometry
        g[0].Radius = radius
        self.holes.Geometry = g

    def setTurn(self, turned):
        placement = self.motion if turned else IDENTITY
        if self.baseOn == "offset":
            self.base.AttachmentOffset = placement
        else:
            self.base.Placement = placement


class E17StaleThenNarrow(TwoStep):
    """First the turn with hole 1 widened to 2 (references that break keep the record of the box
    before the turn); then the hole narrows to 1.5 again, the turn kept: nothing else differs from
    the record but the turn.  The records read it as rigid: heal where the turn carried the
    element, or stay broken."""
    steps = ("turn_widen", "narrow")
    turnedIn = {"turn_widen": True, "narrow": True}
    radiusIn = {"turn_widen": 2.0, "narrow": 1.5}

    def turn_widen(self, doc):
        self.setTurn(True)
        self.setRadius(doc, 2.0)
        doc.recompute()

    def narrow(self, doc):
        self.setRadius(doc, 1.5)
        doc.recompute()


class E18StaleThenTurnBack(TwoStep):
    """First the turn with hole 1 widened (broken references keep their old record); then the box
    is turned back to where it was, the hole still wide: the original with a wide hole 1."""
    steps = ("turn_widen", "back")
    turnedIn = {"turn_widen": True, "back": False}
    radiusIn = {"turn_widen": 2.0, "back": 2.0}

    def turn_widen(self, doc):
        self.setTurn(True)
        self.setRadius(doc, 2.0)
        doc.recompute()

    def back(self, doc):
        self.setTurn(False)
        doc.recompute()


class E19StaleThenTurnBackOffset(E18StaleThenTurnBack):
    baseOn = "offset"


class E20StaleThenNarrowOffset(E17StaleThenNarrow):
    baseOn = "offset"


class E21StaleThenNarrowBodyHeld(E17StaleThenNarrow):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "top", "end_x0", "edge_y0", "corner_000")


SHIFT6 = App.Placement(V(6, 0, 0), App.Rotation())


class G1ThreeHolesShiftedWidenedLast(ThreeHoles):
    """The part shifts by the holes' pitch (6 along x; the holes ride) and the last hole widens.
    hole 1 lands where hole 2 was, hole 2 where hole 3 was."""
    motion = SHIFT6
    AFTER = {"hole3_rim": (18, 5, 10)}

    def other(self, doc):
        g = self.holes.Geometry
        g[2].Radius = 2.0
        self.holes.Geometry = g


class G2ThreeHolesShiftedWidenedLastOffset(G1ThreeHolesShiftedWidenedLast):
    baseOn = "offset"


class G3ThreeHolesShiftedWidenedLastBodyHeld(G1ThreeHolesShiftedWidenedLast):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "hole3_rim", "top", "end_x0", "corner_000")


class G4ThreeHolesShiftedWidenedFirst(ThreeHoles):
    """The part shifts by the pitch and the FIRST hole widens (the referenced one)."""
    motion = SHIFT6
    AFTER = {"hole1_rim": (6, 5, 10)}

    def other(self, doc):
        g = self.holes.Geometry
        g[0].Radius = 2.0
        self.holes.Geometry = g


class G5ThreeHolesShiftedFirstRedrawn(ThreeHoles):
    """The part shifts by the pitch and the first circle is drawn anew."""
    motion = SHIFT6
    ownOrBroken = True

    def other(self, doc):
        self.holes.delGeometry(0)
        self.holes.addGeometry(Part.Circle(V(4, 5, 0), Z, self.holeR), False)


class G6ThreeHolesShiftedFirstRedrawnOffset(G5ThreeHolesShiftedFirstRedrawn):
    baseOn = "offset"


class G7ThreeHolesShiftedFirstRemovedLastMoved(ThreeHoles):
    """The part shifts by the pitch, the first hole is deleted and the last circle moves to
    local x 4: a twin at the first hole's followed place, the real hole gone.  The first
    hole's reference must break (OwnOrBroken of the first hole's followed place: the twin sits
    there, so any answer is the twin; the harness cannot tell it from the hole: expectation is
    BROKEN)."""
    motion = SHIFT6
    AFTER = {"hole3_rim": (5.5, 5, 10)}

    def expect(self, name):
        from PartDesignTests.Scenarios.harness import BROKEN

        if self.stepName and name == "hole1_rim":
            return BROKEN
        return Plate.expect(self, name)

    def other(self, doc):
        g = self.holes.Geometry
        g[2].Center = V(4, 5, 0)
        self.holes.Geometry = g
        self.holes.delGeometry(0)


class J1ToolReplacedByFixedStay(Plate):
    """The turn, and the Pocket's profile replaced by a new sketch fixed in the body with the
    same circles at the same global places (the old tool rode with the part).  A key gone, a key
    added.  The model is globally unchanged; the references stay (a fixed tool)."""
    follow = False
    ownOrBroken = True

    def other(self, doc):
        new = doc.addObject("Sketcher::SketchObject", "Holes2")
        self.body.addObject(new)
        for c in self.circles():
            new.addGeometry(c, False)
        new.MapMode = "Deactivated"
        new.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket.Profile = new


class J2ToolReplacedByFixedFollow(J1ToolReplacedByFixedStay):
    follow = True


class J3ToolReplacedByFixedStayOffset(J1ToolReplacedByFixedStay):
    baseOn = "offset"


class J4ToolReplacedByFixedFollowOffset(J2ToolReplacedByFixedFollow):
    baseOn = "offset"


class J5ToolReplacedByFixedStayBodyHeld(J1ToolReplacedByFixedStay):
    held = "body"
    REFS = ("hole1_rim", "hole2_rim", "top", "end_x0", "edge_y0", "corner_000")
