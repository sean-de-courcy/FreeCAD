# SPDX-License-Identifier: LGPL-2.1-or-later
"""Class D, attacker K8, pass 1 (ops#503): a reference whose element is gone is kept quietly on
another element that an edit put at the old place.

In each case one element (A) loses its exact name: deleted, or removed from its feature. Another
element (B) that keeps its own exact name, and was elsewhere, ends at A's old place: a neighbour
slides in by one pitch. The solver's tier 3 takes B for A at the `same-place` warning level (the
quiet level, taxonomy O8). Where B has its own reference (the control), both references end on
B: two references to two elements collapse onto one. The right answer for A's reference is a
break (or a warned guess of an element nobody else holds).

Verdicts on `integration` 95538c7728 (Windows, V2s), in a comment above each case.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Broken,
    Chamfered,
    ExternalCoincides,
    Filleted,
    Scenario,
    X,
    Z,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m

V = m.V


class SamePlace(Scenario):
    abstract = True
    area = "solver"
    CLASSES = ("D",)
    ISSUE = "ops#503"
    FOUND_BY = "K8 attacker pass 1"
    TIER = "F"
    edited = False


def datumPoint(body, target, sub, mode, name):
    point = body.newObject("PartDesign::Point", name)
    point.AttachmentSupport = [(target, sub)]
    point.MapMode = mode
    return point


def datumPlane(body, target, sub, name="DatumPlane"):
    plane = body.newObject("PartDesign::Plane", name)
    plane.AttachmentSupport = [(target, sub)]
    plane.MapMode = "FlatFace"
    return plane


def fillet(body, target, subs, radius, name="Fillet"):
    f = body.newObject("PartDesign::Fillet", name)
    f.Base = (target, subs)
    f.Radius = radius
    return f


def chamfer(body, target, subs, size, name="Chamfer"):
    c = body.newObject("PartDesign::Chamfer", name)
    c.Base = (target, subs)
    c.Size = size
    return c


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class TwoHoles(SamePlace):
    """A 40 x 20 x 10 block with through holes r = 2 from one pocket sketch: circle 0 at
    (10, 10), circle 1 at (20, 10); datum points at the centres of their top rims."""

    abstract = True
    hole1 = (20, 10)

    def rim0(self):
        return BROKEN if self.edited else edge(center=(10, 10, 10), radius=2)

    def rim1(self):
        return edge(center=(*self.hole1, 10), radius=2)

    def holes(self, doc):
        body = m.body(doc)
        block = m.sketch(doc, "Block", m.rectangle(0, 0, 40, 20), body)
        m.pad(body, block, 10, "BlockPad")
        holes = m.sketch(doc, "Holes", [m.circle(10, 10, 2), m.circle(20, 10, 2)], body, z=10)
        pocket = m.pocketThroughAll(body, holes)
        doc.recompute()
        return body, pocket

    def deleteHole0MoveHole1(self, doc):
        s = doc.Holes
        s.delGeometry(0)  # circle 1 is geometry 0 now, its ID kept
        g = s.Geometry
        g[0].Center = V(10, 10, 0)
        s.Geometry = g
        self.hole1 = (10, 10)
        self.edited = True


# point_hole0 wrong (tier 3 same-place: hole 1's rim), point_hole1 correct (the same edge)
class K8HoleDeletedNeighbourMoved(TwoHoles):
    """Circle 0 is deleted and circle 1 moves to (10, 10): hole 0 is gone, its point must break;
    hole 1's point follows hole 1."""

    AXES = ("M1", "E1", "E4")
    REFS = ("point_hole0", "point_hole1")

    def build(self, doc):
        body, pocket = self.holes(doc)
        p0 = datumPoint(body, pocket, self.names(pocket, self.rim0())[0], "CenterOfCurvature", "Point0")
        p1 = datumPoint(body, pocket, self.names(pocket, self.rim1())[0], "CenterOfCurvature", "Point1")
        self.ref("point_hole0", p0, "AttachmentSupport", self.rim0, Attached())
        self.ref("point_hole1", p1, "AttachmentSupport", self.rim1, Attached())

    edit = TwoHoles.deleteHole0MoveHole1


# chamfer_hole0 wrong, point_hole0 wrong (tier 3 same-place: hole 1's rim), point_hole1 correct
class K8HoleRedrawnNeighbourMoved(TwoHoles):
    """A chamfer 0.5 on hole 0's top rim too. Circle 0 is deleted, circle 1 moves to (10, 10), and
    a new circle is drawn at (30, 10): hole 0's references must break, or be guessed onto the new
    hole with a warning; never onto hole 1, whose own point follows it."""

    AXES = ("M1", "E5", "E4")
    REFS = ("chamfer_hole0", "point_hole0", "point_hole1")

    def rim0(self):
        if self.edited:
            return Broken(edge(center=(30, 10, 10), radius=2))
        return edge(center=(10, 10, 10), radius=2)

    def build(self, doc):
        body, pocket = self.holes(doc)
        p0 = datumPoint(body, pocket, self.names(pocket, self.rim0())[0], "CenterOfCurvature", "Point0")
        p1 = datumPoint(body, pocket, self.names(pocket, self.rim1())[0], "CenterOfCurvature", "Point1")
        c = chamfer(body, pocket, self.names(pocket, self.rim0()), 0.5)
        self.ref("chamfer_hole0", c, "Base", self.rim0, Chamfered(0.5))
        self.ref("point_hole0", p0, "AttachmentSupport", self.rim0, Attached())
        self.ref("point_hole1", p1, "AttachmentSupport", self.rim1, Attached())

    def edit(self, doc):
        self.deleteHole0MoveHole1(doc)
        doc.Holes.addGeometry(m.circle(30, 10, 2), False)


# external_hole0 wrong (tier 3 same-place: hole 1's rim), external_hole1 correct
class K8ExternalHoleNeighbourMoved(TwoHoles):
    """The references are two sketches' external geometry: Ext0 projects hole 0's top rim, Ext1
    hole 1's. Circle 0 is deleted and circle 1 moves to (10, 10)."""

    AXES = ("M8", "E1", "E4")
    REFS = ("external_hole0", "external_hole1")

    def build(self, doc):
        body, pocket = self.holes(doc)
        e0 = m.sketch(doc, "Ext0", [], body, z=10)
        e0.addExternal(pocket.Name, self.names(pocket, self.rim0())[0])
        e1 = m.sketch(doc, "Ext1", [], body, z=10)
        e1.addExternal(pocket.Name, self.names(pocket, self.rim1())[0])
        self.ref("external_hole0", e0, "ExternalGeometry", self.rim0, ExternalCoincides())
        self.ref("external_hole1", e1, "ExternalGeometry", self.rim1, ExternalCoincides())

    edit = TwoHoles.deleteHole0MoveHole1


# point_pin0 wrong (tier 3 same-place: pin 1's rim), point_pin1 correct
class K8FusePinRemovedNeighbourMoved(SamePlace):
    """A Part MultiFuse of a 40 x 20 x 10 box and two pins (cylinders r = 2, 5 high) standing on
    it at (10, 10) and (20, 10); a body based on the fuse has datum points at the centres of the
    pins' top rims. Pin 0 is taken out of the fuse and pin 1 moves to (10, 10): pin 0's point
    must break, pin 1's follows pin 1."""

    AXES = ("M4", "E1", "E4")
    REFS = ("point_pin0", "point_pin1")
    pin1 = (20, 10)

    def rim0(self):
        return BROKEN if self.edited else edge(center=(10, 10, 15), radius=2)

    def rim1(self):
        return edge(center=(*self.pin1, 15), radius=2)

    def build(self, doc):
        plate = m.box(doc, "Plate", (40, 20, 10))
        pins = []
        for i, (x, y) in enumerate(((10, 10), (20, 10))):
            pin = doc.addObject("Part::Cylinder", f"Pin{i}")
            pin.Radius, pin.Height = 2, 5
            pin.Placement.Base = V(x, y, 10)
            pins.append(pin)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [plate] + pins
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        p0 = datumPoint(body, base, self.names(base, self.rim0())[0], "CenterOfCurvature", "Point0")
        p1 = datumPoint(body, base, self.names(base, self.rim1())[0], "CenterOfCurvature", "Point1")
        self.ref("point_pin0", p0, "AttachmentSupport", self.rim0, Attached())
        self.ref("point_pin1", p1, "AttachmentSupport", self.rim1, Attached())

    def edit(self, doc):
        doc.Fuse.Shapes = [doc.Plate, doc.Pin1]
        doc.Pin1.Placement.Base = V(10, 10, 10)
        self.pin1 = (10, 10)
        self.edited = True


# point_hole0 wrong (tier 3 same-place: hole 1's rim), point_hole1 correct
class K8OffsetHoleRemovedNeighbourMoved(SamePlace):
    """A 40 x 20 x 10 box minus cylinders r = 3 at (10, 10) and (20, 10) (a Part Cut of the box and
    a MultiFuse of the tools; a third tool at x = 100 cuts nothing), offset outwards by 1 (Part
    Offset, Intersection join): holes r = 2, top at z = 11. A body based on the offset has datum
    points at the centres of the holes' top rims. Tool 0 is taken out and tool 1 moves to
    (10, 10): hole 0's point must break, hole 1's follows hole 1."""

    AXES = ("M6", "E1", "E4")
    REFS = ("point_hole0", "point_hole1")
    hole1 = (20, 10)

    def rim0(self):
        return BROKEN if self.edited else edge(center=(10, 10, 11), radius=2)

    def rim1(self):
        return edge(center=(*self.hole1, 11), radius=2)

    def build(self, doc):
        block = m.box(doc, "Block", (40, 20, 10))
        tools = []
        for i, (x, y) in enumerate(((10, 10), (20, 10), (100, 10))):
            c = doc.addObject("Part::Cylinder", f"Tool{i}")
            c.Radius, c.Height = 3, 20
            c.Placement.Base = V(x, y, -5)
            tools.append(c)
        fused = doc.addObject("Part::MultiFuse", "Tools")
        fused.Shapes = tools
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = block, fused
        offset = doc.addObject("Part::Offset", "Offset")
        offset.Source = cut
        offset.Value = 1
        offset.Join = "Intersection"
        body = m.body(doc)
        body.BaseFeature = offset
        doc.recompute()
        base = featureBase(body)
        p0 = datumPoint(body, base, self.names(base, self.rim0())[0], "CenterOfCurvature", "Point0")
        p1 = datumPoint(body, base, self.names(base, self.rim1())[0], "CenterOfCurvature", "Point1")
        self.ref("point_hole0", p0, "AttachmentSupport", self.rim0, Attached())
        self.ref("point_hole1", p1, "AttachmentSupport", self.rim1, Attached())

    def edit(self, doc):
        doc.Tools.Shapes = [doc.Tool1, doc.Tool2]
        doc.Tool1.Placement.Base = V(10, 10, -5)
        self.hole1 = (10, 10)
        self.edited = True


# A profile 30 wide, 5 high, with two ridges 3 high on top: A at 10..14, B at 20..24
RIDGES = [
    (0, 0), (30, 0), (30, 5), (24, 5), (24, 8), (20, 8), (20, 5), (14, 5), (14, 8), (10, 8),
    (10, 5), (0, 5),
]


def removeRidgeA(sketch):
    """Ridge A's three lines and the floor between the ridges are deleted, and ridge B slides
    (IDs kept) to 10..14, where A was."""
    for geoId in (9, 8, 7, 6):
        sketch.delGeometry(geoId)
    m.setLines(sketch, {
        2: ((30, 5), (14, 5)),
        3: ((14, 5), (14, 8)),
        4: ((14, 8), (10, 8)),
        5: ((10, 8), (10, 5)),
    })


# fillet_ridgeA wrong (tier 3 same-place: ridge B's edge), external_ridgeB correct
class K8RevolvedRidgeRemovedNeighbourMoved(SamePlace):
    """The ridged profile in the XZ plane (x the radius, from the axis), revolved 360 degrees
    about Z: a disc with two ring ridges. A fillet r = 0.5 on ridge A's outer top edge (circle
    r = 14, z = 8); a sketch projects ridge B's (r = 24). Ridge A is removed and B slides into its
    place: A's fillet must break, B's projection follows B."""

    AXES = ("M7", "E1", "E4")
    REFS = ("fillet_ridgeA", "external_ridgeB")
    rB = 24

    def edgeA(self):
        return BROKEN if self.edited else edge(center=(0, 0, 8), radius=14)

    def edgeB(self):
        return edge(center=(0, 0, 8), radius=self.rB)

    def build(self, doc):
        body = m.body(doc)
        placement = App.Placement(V(0, 0, 0), m.rotationFromAxes((1, 0, 0), (0, 0, 1)))
        profile = m.sketch(doc, "Profile", m.polygon(RIDGES), body, placement=placement)
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = profile
        rev.ReferenceAxis = (m.originFeature(body, "Z_Axis"), [""])
        rev.Angle = 360
        doc.recompute()
        ext = m.sketch(doc, "ExtB", [], body, z=8)
        ext.addExternal(rev.Name, self.names(rev, self.edgeB())[0])
        f = fillet(body, rev, self.names(rev, self.edgeA()), 0.5)
        self.ref("fillet_ridgeA", f, "Base", self.edgeA, Filleted(0.5))
        self.ref("external_ridgeB", ext, "ExternalGeometry", self.edgeB, ExternalCoincides())

    def edit(self, doc):
        removeRidgeA(doc.Profile)
        self.rB = 14
        self.edited = True


# fillet_ridgeA wrong (tier 3 same-place: ridge B's edge), point_ridgeB correct
class K8SweptRidgeRemovedNeighbourMoved(SamePlace):
    """The ridged profile in the XY plane swept (PartDesign AdditivePipe, right corners) along an
    L spine: 40 up Z, then 40 along -Y. A fillet r = 0.5 on ridge A's outer top edge in the first
    leg (along Z through (14, 8)); a datum point at the middle of ridge B's (through (24, 8)).
    Ridge A is removed and B slides into its place: A's fillet must break, B's point follows B."""

    AXES = ("M3", "E1", "E4")
    REFS = ("fillet_ridgeA", "point_ridgeB")
    xB = 24

    def edgeA(self):
        return BROKEN if self.edited else edge(direction=Z, through=(14, 8, 0))

    def edgeB(self):
        return edge(direction=Z, through=(self.xB, 8, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.polygon(RIDGES), body)
        placement = App.Placement(V(0, 0, 0), m.rotationFromAxes((0, 1, 0), (0, 0, 1)))
        spine = m.sketch(doc, "Spine", m.polyline([(0, 0), (0, 40), (-40, 40)]), body,
                         placement=placement)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1", "Edge2"])
        pipe.Transition = "Right corner"
        doc.recompute()
        point = datumPoint(body, pipe, self.names(pipe, self.edgeB())[0], "CenterOfMass", "PointB")
        f = fillet(body, pipe, self.names(pipe, self.edgeA()), 0.5)
        self.ref("fillet_ridgeA", f, "Base", self.edgeA, Filleted(0.5))
        self.ref("point_ridgeB", point, "AttachmentSupport", self.edgeB, Attached())

    def edit(self, doc):
        removeRidgeA(doc.Profile)
        self.xB = 14
        self.edited = True


class TwinBosses(SamePlace):
    """A 40 x 20 x 5 plate with two bosses r = 3, 5 high, from one sketch: circle 0 at (10, 10),
    circle 1 at (30, 10)."""

    abstract = True

    def bosses(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 40, 20), body)
        m.pad(body, plate, 5, "PlatePad")
        circles = m.sketch(doc, "Circles", [m.circle(10, 10, 3), m.circle(30, 10, 3)], body, z=5)
        bosses = m.pad(body, circles, 5, "Bosses")
        doc.recompute()
        return body, bosses


# Step trade: fillet_boss1 broken, point_boss1 broken, point_boss0 broken (the solver refuses
# the trade: "moved 20.000 mm; ... sits where it was"; loud, right element among the candidates).
# Step redraw: fillet_boss1 wrong, point_boss1 wrong (the broken references are taken, tier 3
# same-place, for boss 0's edge at boss 1's original place), point_boss0 broken.
class K8TwinTradeThenRedraw(TwinBosses):
    """A fillet r = 0.5 on boss 1's top edge, datum points at the centres of both bosses' top
    edges. The bosses trade places (IDs kept; the solver breaks all three references loudly),
    then circle 1 (now at (10, 10)) is deleted and drawn again there. Boss 1's references must
    stay broken, or be guessed onto the redrawn boss; never onto boss 0, now at boss 1's original
    place, which has its own reference."""

    AXES = ("M1", "E4", "E5")
    REFS = ("fillet_boss1", "point_boss1", "point_boss0")
    steps = ("trade", "redraw")
    boss0, boss1 = (10, 10), (30, 10)

    def edge1(self):
        if self.edited:
            return Broken(edge(center=(10, 10, 10), radius=3))
        return edge(center=(*self.boss1, 10), radius=3)

    def edge0(self):
        return edge(center=(*self.boss0, 10), radius=3)

    def build(self, doc):
        body, bosses = self.bosses(doc)
        p0 = datumPoint(body, bosses, self.names(bosses, self.edge0())[0], "CenterOfCurvature", "Point0")
        p1 = datumPoint(body, bosses, self.names(bosses, self.edge1())[0], "CenterOfCurvature", "Point1")
        f = fillet(body, bosses, self.names(bosses, self.edge1()), 0.5)
        self.ref("fillet_boss1", f, "Base", self.edge1, Filleted(0.5))
        self.ref("point_boss1", p1, "AttachmentSupport", self.edge1, Attached())
        self.ref("point_boss0", p0, "AttachmentSupport", self.edge0, Attached())

    def trade(self, doc):
        s = doc.Circles
        g = s.Geometry  # the circles keep their IDs
        g[0].Center = V(30, 10, 0)
        g[1].Center = V(10, 10, 0)
        s.Geometry = g
        self.boss0, self.boss1 = (30, 10), (10, 10)

    def redraw(self, doc):
        s = doc.Circles
        s.delGeometry(1)
        s.addGeometry(m.circle(10, 10, 3), False)
        self.edited = True


# fillet_corner wrong (tier 3 same-place: the new square's edge at (10, 10), between its -X and
# +Y faces), plane_right broken (right: no face at x = 10 faces +X any more)
class K8SquareRedrawnBesideItself(SamePlace):
    """A 10 x 10 square padded 10; a fillet on the vertical edge at (10, 10), between the +X and
    +Y faces, and a datum plane on the face x = 10. The square is deleted and drawn again at
    x 10..20 (from another corner, the other way round): every name is new, and the new square's
    edge between its -X and +Y faces is where the referenced edge was. Right: a break, or a warned
    guess of the edge at (20, 10) that plays the old one's part; never the edge at the old place,
    whose faces face the other way."""

    AXES = ("M1", "E4", "E5")
    REFS = ("fillet_corner", "plane_right")

    def corner(self):
        if self.edited:
            return Broken(edge(direction=Z, through=(20, 10, 0)))
        return edge(direction=Z, through=(10, 10, 0))

    def right(self):
        if self.edited:
            return Broken(face(normal=X, through=(20, 0, 0)))
        return face(normal=X, through=(10, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 10, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        plane = datumPlane(body, pad, self.names(pad, self.right())[0])
        f = fillet(body, pad, self.names(pad, self.corner()), 1)
        self.ref("fillet_corner", f, "Base", self.corner, Filleted(1))
        self.ref("plane_right", plane, "AttachmentSupport", self.right, Attached())

    def edit(self, doc):
        s = doc.Profile
        for geoId in reversed(range(s.GeometryCount)):
            s.delGeometry(geoId)
        s.addGeometry(m.polygon([(20, 10), (20, 0), (10, 0), (10, 10)]), False)
        self.edited = True
