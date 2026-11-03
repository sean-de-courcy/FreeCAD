# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2js (review pr390-r2js): attacks on `takenOnIntegration` (the narrowed
contest of a pick the twin clause broke) with the model of review390r2h/r2hs.

A Pad (Refine off) from an unattached sketch (rectangle x -3..3, y -0.5..0.5) up to a Part::Feature
shell at z = 10: the plate x -10..20, y -10..10 with a rectangular hole x -1..1, y -2..2 and its fill,
so the Pad's far edge y 0.5 comes in pieces L (x -3..-1), M (the fill, -1..1) and R (1..3). Pocket
circles r 0.3 centred at y 0.6 (half chord H = sqrt(0.08) on y 0.5), one sketch, one Pocket:
A at (-1.82, 0.6) (two crossings of L, twins), B at (-1.2, 0.6) (-1.4828 on L, -0.9172 on M),
C at (2, 0.6) (1.7172, 2.2828 on R). References: the six crossings, each its own datum point
(the "Six" cases), or two in one owner (a sketch attached at the first, the second its external
vertex: the forced matching runs over both).

Each edit is a list of operations on circles by tag; the expectation follows the circle by tag
(moved or resized: its crossing's new place or a break; unchanged: its place; redrawn in place: its
place or a break (decision 227); deleted: a break).
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
R0 = 0.3
CY = 0.6
START = {"A": (-1.82, CY, R0), "B": (-1.2, CY, R0), "C": (2.0, CY, R0)}


def half(r):
    return (r * r - (CY - 0.5) ** 2) ** 0.5


REF_SIDE = {
    "a_left": ("A", -1),
    "a_right": ("A", 1),
    "b_left": ("B", -1),
    "b_right": ("B", 1),
    "c_left": ("C", -1),
    "c_right": ("C", 1),
}


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2js"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("a_left", "a_right", "b_left", "b_right", "c_left", "c_right")
    OWNERS = "datum"  # "datum": one datum point per reference; "pair": first/second in one owner
    OPS = ()
    HOLES = ((-1, -2, 1, 2),)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x):
        return vertex(self.P(x, 0.5))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self):
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        wires = [outer]
        fills = []
        for hx0, hy0, hx1, hy1 in self.HOLES:
            wires.append(self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)]))
            fills.append(
                Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]))
                .toNurbs()
                .Faces[0]
            )
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), wires).toNurbs().Faces[0]
        return Part.Shell([plate] + fills)

    def before(self, name):
        tag, side = REF_SIDE[name]
        x, y, r = START[tag]
        return x + side * half(r)

    def build(self, doc):
        self.edited = False
        self.tags = ["A", "B", "C"]
        self.now = dict(START)
        self.redrawn = set()
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(self.S(-3), self.S(-0.5), self.S(3), self.S(0.5)), body
        )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.profile
        pad.Type = "UpToShape"
        pad.UpToShape = (self.plate, ["Face%d" % (i + 1) for i in range(len(self.plate.Shape.Faces))])
        pad.Refine = False
        doc.recompute()
        self.hole = m.sketch(
            doc,
            "Circles",
            [m.circle(self.S(START[t][0]), self.S(CY), self.S(START[t][2])) for t in self.tags],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        target = self.addLater(body, pocket)
        subs = {n: self.names(target, self.place(self.before(n)))[0] for n in self.REFS}
        if self.OWNERS == "pair":
            first, second = self.REFS
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(target, subs[first])]
            probe.MapMode = "Translate"
            probe.addExternal(target.Name, subs[second])
            self.ref(first, probe, "AttachmentSupport", self.expectation(first), Attached())
            self.ref(second, probe, "ExternalGeometry", self.expectation(second))
        else:
            for name in self.REFS:
                point = body.newObject("PartDesign::Point", "On" + name)
                point.AttachmentSupport = [(target, subs[name])]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    LATER = ()  # circles (x, r) of a second sketch, cut by a second Pocket after the first

    def addLater(self, body, pocket):
        if not self.LATER:
            return pocket
        sketch = m.sketch(
            body.Document,
            "Circles2",
            [m.circle(self.S(x), self.S(CY), self.S(r)) for x, r in self.LATER],
            body,
            z=self.S(HEIGHT),
        )
        later = body.newObject("PartDesign::Pocket", "Pocket2")
        later.Profile = sketch
        later.Type = 0
        later.Length = self.S(2)
        later.Refine = False
        body.Document.recompute()
        self.sketch2 = sketch
        return later

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(self.before(name))
            tag, side = REF_SIDE[name]
            if tag in self.redrawn:
                return OwnOrBroken(self.place(self.before(name)))
            if tag not in self.now:
                return BROKEN
            x, y, r = self.now[tag]
            if (x, r) == (START[tag][0], START[tag][2]):
                return self.place(self.before(name))
            return OwnOrBroken(self.place(x + side * half(r)))

        return expect

    # operations
    def index(self, tag):
        return self.tags.index(tag)

    def move(self, tag, x):
        geometry = self.hole.Geometry
        geometry[self.index(tag)].Center = V(self.S(x), self.S(CY), 0)
        self.hole.Geometry = geometry
        _, y, r = self.now[tag]
        self.now[tag] = (x, y, r)

    def resize(self, tag, r):
        geometry = self.hole.Geometry
        geometry[self.index(tag)].Radius = self.S(r)
        self.hole.Geometry = geometry
        x, y, _ = self.now[tag]
        self.now[tag] = (x, y, r)

    def delete(self, tag):
        self.hole.delGeometry(self.index(tag))
        self.tags.remove(tag)
        self.now.pop(tag)

    def add(self, tag, x, r=R0):
        self.hole.addGeometry(m.circle(self.S(x), self.S(CY), self.S(r)), False)
        self.tags.append(tag)
        self.now[tag] = (x, CY, r)

    def redraw(self, tag):
        x, y, r = self.now[tag]
        self.delete(tag)
        self.add(tag, x, r)
        self.redrawn.add(tag)

    def change(self, doc):
        raise NotImplementedError

    def edit(self, doc):
        self.change(doc)
        self.edited = True


EDITS = {}


def edit(name):
    def wrap(function):
        EDITS[name] = function
        return function

    return wrap


@edit("DelBRedrawA")
def _(s):
    s.delete("B")
    s.redraw("A")


@edit("MoveBRight")
def _(s):
    s.move("B", -0.8)


@edit("MoveALeft")
def _(s):
    s.move("A", -2.12)


@edit("MoveAOffNewAtPlace")
def _(s):
    s.move("A", -2.6)
    s.add("N", -1.82)


@edit("RedrawAB")
def _(s):
    s.redraw("A")
    s.redraw("B")


@edit("RedrawA")
def _(s):
    s.redraw("A")


@edit("RedrawB")
def _(s):
    s.redraw("B")


@edit("SwapAB")
def _(s):
    s.move("A", -1.2 + 0.0)  # overlaps B until B moves: set B first
    s.move("B", -1.82)


@edit("ResizeA")
def _(s):
    s.resize("A", 0.31)


@edit("DelA")
def _(s):
    s.delete("A")


@edit("DelB")
def _(s):
    s.delete("B")


@edit("DelABNewBetween")
def _(s):
    s.delete("A")
    s.delete("B")
    s.add("N", -1.51)


@edit("NewNearAOnLeft")
def _(s):
    s.add("N", -2.45)


@edit("MoveAOffRedrawB")
def _(s):
    s.move("A", -2.6)
    s.redraw("B")


@edit("MoveAOffDelBNewAtA")
def _(s):
    s.move("A", -2.6)
    s.delete("B")
    s.add("N", -1.82)


@edit("DelANewAtB")
def _(s):
    s.delete("A")
    s.move("B", -1.82)
    s.add("N", -1.2)


PAIRS = {
    "AR_BL": ("a_right", "b_left"),
    "BL_AR": ("b_left", "a_right"),
    "AL_AR": ("a_left", "a_right"),
    "BL_BR": ("b_left", "b_right"),
}


def make(editName, owners, pair=None):
    function = EDITS[editName]
    attrs = {
        "__doc__": "review pr390-r2js: %s, %s" % (editName, pair or "six datum points"),
        "OWNERS": owners,
        "change": lambda self, doc, f=function: f(self),
    }
    if pair:
        attrs["REFS"] = PAIRS[pair]
    return type("R2js%s%s" % (editName, "".join(w.title() for w in (pair or "Six").split("_"))), (Base,), attrs)


for _name in EDITS:
    _c = make(_name, "datum")
    globals()[_c.__name__] = _c
    for _pair in PAIRS:
        _c = make(_name, "pair", _pair)
        globals()[_c.__name__] = _c

for _name in EDITS:
    for _ref in REF_SIDE:
        _c = type(
            "R2jsSolo%s%s" % (_name, "".join(w.title() for w in _ref.split("_"))),
            (Base,),
            {
                "__doc__": "review pr390-r2js: %s, %s alone" % (_name, _ref),
                "REFS": (_ref,),
                "change": lambda self, doc, f=EDITS[_name]: f(self),
            },
        )
        globals()[_c.__name__] = _c

LATERS = {"DL": ((-2.6, 0.3),), "DM": ((-0.45, 0.3),), "DR": ((-1.9, 0.12),)}
for _later, _circles in LATERS.items():
    for _name in ("DelA", "DelB", "DelBRedrawA", "RedrawA", "MoveAOffNewAtPlace", "MoveALeft", "DelABNewBetween", "RedrawAB"):
        # A moved left onto the later pocket's circle at DL and DR: the Pad's up-to link goes
        # out of scope and the model doesn't build (an `error` on both builds), so left out
        if _name == "MoveALeft" and _later in ("DL", "DR"):
            continue
        _specs = [("Six", None, "datum")] + [(k, k, "pair") for k in PAIRS]
        for _label, _pair, _owners in _specs:
            _attrs = {
                "__doc__": "review pr390-r2js: %s, later pocket %s, %s" % (_name, _later, _label),
                "OWNERS": _owners,
                "LATER": _circles,
                "change": lambda self, doc, f=EDITS[_name]: f(self),
            }
            if _pair:
                _attrs["REFS"] = PAIRS[_pair]
            _c = type("R2js%s%s%s" % (_later, _name, "".join(w.title() for w in _label.split("_"))), (Base,), _attrs)
            globals()[_c.__name__] = _c

del _c, _name, _pair, _ref, _later, _circles, _specs, _label, _owners, _attrs
