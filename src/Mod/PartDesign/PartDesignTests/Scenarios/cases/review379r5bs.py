# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr379-r5bs: the reverse of round 5's raise: a copy's top rim put on a gone copy's bottom
rim (the sketch's own circle, a Pad-modified edge) and a copy's bottom rim on a gone copy's top
rim, with the pins floating or standing; pad/pocket siblings of one sketch."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    BROKEN,
    OwnOrBroken,
    Scenario,
    edge,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector


def datumPoint(body, target, sub, name):
    point = body.newObject("PartDesign::Point", name)
    point.AttachmentSupport = [(target, sub)]
    point.MapMode = "CenterOfCurvature"
    return point


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class Floating(Scenario):
    """Two links to a pin body (a pad 5 of a circle r = 2 in PinSketch) floating at z = 10 at
    x = 10, 20 in a MultiFuse with a long plate far off; datum points on each copy's top rim
    (kind 'top', z = base + 5) or bottom rim (kind 'bottom', z = base) per REFS."""

    abstract = True
    area = "review-r5bs"
    CLASSES = ("D",)
    AXES = ("M5", "E1", "E4", "X4:4000")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5bs"
    TIER = "F"
    REFS = ("top_copy0", "top_copy1", "bottom_copy0", "bottom_copy1")
    plate = (4000, 20, 10)
    scale = 1

    def rim(self, k, kind):
        place = self.at.get(k)
        if place is None:
            return BROKEN
        x, z = place
        return edge(center=(x, 10, z + (5 if kind == "top" else 0)), radius=2)

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", self.plate, at=(0, 100, 0))
        pin = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pin)
        m.pad(pin, sketch, 5, "PinPad")
        doc.recompute()
        self.pinBody = pin
        for k, (x, z) in self.at.items():
            link = doc.addObject("App::Link", f"Copy{k}")
            link.LinkedObject = pin
            link.Placement.Base = V(x, 10, z)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [doc.Plate, doc.Copy0, doc.Copy1]
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        for kind in ("top", "bottom"):
            for k in (0, 1):
                point = datumPoint(
                    body, base, self.names(base, self.rim(k, kind))[0], f"{kind}{k}"
                )
                self.ref(
                    f"{kind}_copy{k}",
                    point,
                    "AttachmentSupport",
                    lambda k=k, kind=kind: self.rim(k, kind),
                    Attached(),
                )

    def leave0(self, doc):
        doc.Fuse.Shapes = [doc.Plate, doc.Copy1]
        self.at[0] = None


class FloatRaised(Floating):
    """Copy 0 leaves, copy 1 up by 5: its bottom rim on copy 0's top rim."""

    def edit(self, doc):
        self.leave0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 15)
        self.at[1] = (10, 15)


class FloatLowered(Floating):
    """Copy 0 leaves, copy 1 down by 5 (and onto x = 10): its top rim on copy 0's bottom rim."""

    def edit(self, doc):
        self.leave0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 5)
        self.at[1] = (10, 5)


class FloatLoweredSmall(FloatLowered):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class FloatRaisedSmall(FloatRaised):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class FloatSlid(Floating):
    """Copy 0 leaves, copy 1 slides to x = 10 at the same height: top onto top, bottom onto
    bottom. All of copy 0's points break (the same-maker twin case)."""

    def edit(self, doc):
        self.leave0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = (10, 10)


class FloatSlidSmall(FloatSlid):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class TwoPinBodiesSlid(Floating):
    """The control without links: two bodies from two sketches."""

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", self.plate, at=(0, 100, 0))
        pins = []
        for k, (x, z) in self.at.items():
            pin = m.body(doc)
            sketch = m.sketch(doc, f"PinSketch{k}", [m.circle(0, 0, 2)], pin)
            m.pad(pin, sketch, 5, f"PinPad{k}")
            pin.Placement.Base = V(x, 10, z)
            pins.append(pin)
        self.pins = pins
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [doc.Plate] + pins
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        for kind in ("top", "bottom"):
            for k in (0, 1):
                point = datumPoint(
                    body, base, self.names(base, self.rim(k, kind))[0], f"{kind}{k}"
                )
                self.ref(f"{kind}_copy{k}", point, "AttachmentSupport",
                         lambda k=k, kind=kind: self.rim(k, kind), Attached())

    def leave0(self, doc):
        doc.Fuse.Shapes = [doc.Plate, self.pins[1]]
        self.at[0] = None

    def edit(self, doc):
        self.leave0(doc)
        self.pins[1].Placement.Base = V(10, 10, 15)
        self.at[1] = (10, 15)


class TwoPinBodiesLowered(TwoPinBodiesSlid):
    def edit(self, doc):
        self.leave0(doc)
        self.pins[1].Placement.Base = V(10, 10, 5)
        self.at[1] = (10, 5)


class ScaleLowered(Floating):
    """Copy 0 is a Part::Scale (factor 1) of the pin body, copy 1 a link: copy 0 leaves, the link goes
    down by 5 onto x = 10: its top rim on the Scale copy's bottom rim."""

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", self.plate, at=(0, 100, 0))
        pin = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pin)
        m.pad(pin, sketch, 5, "PinPad")
        doc.recompute()
        scale = doc.addObject("Part::Scale", "Copy0")
        scale.Base = pin
        scale.Uniform = True
        scale.UniformScale = 1
        scale.Placement.Base = V(10, 10, 10)
        link = doc.addObject("App::Link", "Copy1")
        link.LinkedObject = pin
        link.Placement.Base = V(20, 10, 10)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [doc.Plate, doc.Copy0, doc.Copy1]
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        for kind in ("top", "bottom"):
            for k in (0, 1):
                point = datumPoint(
                    body, base, self.names(base, self.rim(k, kind))[0], f"{kind}{k}"
                )
                self.ref(f"{kind}_copy{k}", point, "AttachmentSupport",
                         lambda k=k, kind=kind: self.rim(k, kind), Attached())

    def edit(self, doc):
        self.leave0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 5)
        self.at[1] = (10, 5)


class ScaleLoweredSmall(ScaleLowered):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class ArrayLowered(Floating):
    """A link array of two pins (x = 10, 20); the count goes 2 -> 1 and element 0 goes to x = 20,
    z = 5: its top rim on element 1's bottom rim. Element 1's points break."""

    REFS = ("top_copy0", "top_copy1", "bottom_copy0", "bottom_copy1")

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", self.plate, at=(0, 100, 0))
        pin = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pin)
        m.pad(pin, sketch, 5, "PinPad")
        doc.recompute()
        array = doc.addObject("App::Link", "Array")
        array.LinkedObject = pin
        array.ElementCount = 2
        array.ShowElement = False
        doc.recompute()
        array.PlacementList = [
            App.Placement(V(10, 10, 10), App.Rotation()),
            App.Placement(V(20, 10, 10), App.Rotation()),
        ]
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [doc.Plate, array]
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        for kind in ("top", "bottom"):
            for k in (0, 1):
                point = datumPoint(
                    body, base, self.names(base, self.rim(k, kind))[0], f"{kind}{k}"
                )
                self.ref(f"{kind}_copy{k}", point, "AttachmentSupport",
                         lambda k=k, kind=kind: self.rim(k, kind), Attached())

    def edit(self, doc):
        doc.Array.ElementCount = 1
        doc.Array.PlacementList = [App.Placement(V(20, 10, 5), App.Rotation())]
        self.at = {0: (20, 5), 1: None}


class ArrayLoweredSmall(ArrayLowered):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class ArrayRaised(ArrayLowered):
    """As ArrayLowered, element 0 goes to x = 20, z = 15: its bottom rim on element 1's top rim."""

    def edit(self, doc):
        doc.Array.ElementCount = 1
        doc.Array.PlacementList = [App.Placement(V(20, 10, 15), App.Rotation())]
        self.at = {0: (20, 15), 1: None}


class ArrayRaisedSmall(ArrayRaised):
    plate = (40, 20, 10)
    AXES = ("M5", "E1", "X4:60")


class BossLowered(Scenario):
    """One Body: a long plate (a pad), a boss (a pad of a circle r = 2 at (10, 10), 5 high, on the
    plate top z = 10) and a second boss at x = 20. Datum points on boss 0's bottom rim (the
    junction circle, z = 10) and top rim. Edit: boss 0's sketch goes down by 5, so its top rim lies
    where its bottom rim was (the pad is fused into the plate, Refine off). The bottom rim's name
    is gone; the top rim is the pad's extrusion of the same sketch circle."""

    area = "review-r5bs"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "X4:4000")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5bs"
    TIER = "F"
    REFS = ("bottom0", "top0")
    length = 4000
    zs = 10

    def rim(self, kind):
        if kind == "bottom":
            return BROKEN if self.zs != 10 else edge(center=(10, 10, 10), radius=2)
        return edge(center=(10, 10, self.zs + 5), radius=2)

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "PlateSketch", m.rectangle(0, 0, self.length, 20), body)
        m.pad(body, plate, 10, "Plate").Refine = False
        s0 = m.sketch(doc, "Boss0", [m.circle(10, 10, 2)], body, z=10)
        self.pad0 = m.pad(body, s0, 5, "BossPad0")
        self.pad0.Refine = False
        s1 = m.sketch(doc, "Boss1", [m.circle(20, 10, 2)], body, z=10)
        pad1 = m.pad(body, s1, 5, "BossPad1")
        pad1.Refine = False
        doc.recompute()
        for kind in ("bottom", "top"):
            point = body.newObject("PartDesign::Point", f"{kind}Point")
            point.AttachmentSupport = [(pad1, self.names(pad1, self.rim(kind))[0])]
            point.MapMode = "CenterOfCurvature"
            self.ref(f"{kind}0", point, "AttachmentSupport",
                     lambda kind=kind: self.rim(kind), Attached())

    def edit(self, doc):
        sketch = doc.Boss0
        p = sketch.Placement
        p.Base = V(0, 0, 5)
        sketch.Placement = p
        self.zs = 5


class BossLoweredSmall(BossLowered):
    length = 40
    AXES = ("M1", "E1", "X4:60")
