# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr379-r5b: the fix of round 5 (PLAN decision 184: XP's place pick of another origin breaks
under T1'). Copies whose maker is gone while the sketch lives, through other copy mechanisms (a link
array, SubShapeBinders), a body's own feature replaced, and Tier1SameMaker off (the Tier1SameSource-off
case, XP's warned resolution that decision 184 keeps, is not a corpus key).

The pin is a PartDesign Body: a pad 5 high of a circle r = 2 (PinSketch). Copies stand on a
3000 x 2000 x 10 plate (d_max ~36 mm) at (x, 10, 10) in a Part::MultiFuse (or a Compound); a Body on
the result has datum points at the centres of the copies' top rims (z = 15). The pin's bottom rim,
5 mm below its top rim, lies within d_max, so tier 3's gap test refuses there and XP decides on the
PR, where `integration` breaks.
"""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Scenario,
    edge,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
SOLVER_GROUP = "User parameter:BaseApp/Preferences/Mod/Part/NamingSolver"


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class RaisedCopies(Scenario):
    abstract = True
    area = "review-r5b-links"
    CLASSES = ("D",)
    AXES = ("M5", "E1", "E4", "X4:4000")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5b"
    TIER = "F"
    REFS = ("point_copy0", "point_copy1")
    plate = (3000, 2000, 10)
    start = (10, 20)
    maker = "Part::MultiFuse"
    switches = {}

    def rim(self, k):
        x = self.at.get(k)
        if x is None:
            return BROKEN
        return edge(center=(x, 10, self.z.get(k, 15)), radius=2)

    def makePin(self, doc):
        pin = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pin)
        m.pad(pin, sketch, 5, "PinPad")
        doc.recompute()
        self.pin = pin

    def makeCopies(self, doc):
        copies = []
        for k, x in enumerate(self.start):
            link = doc.addObject("App::Link", f"Copy{k}")
            link.LinkedObject = self.pin
            link.Placement.Base = V(x, 10, 10)
            copies.append(link)
        return copies

    def setInputs(self, doc, objs):
        if self.maker == "Part::MultiFuse":
            doc.Maker.Shapes = objs
        else:
            doc.Maker.Links = objs

    def build(self, doc):
        self.at = dict(enumerate(self.start))
        self.z = {}
        m.box(doc, "Plate", self.plate)
        self.makePin(doc)
        copies = self.makeCopies(doc)
        doc.addObject(self.maker, "Maker")
        self.setInputs(doc, [doc.Plate] + copies)
        body = m.body(doc)
        body.BaseFeature = doc.Maker
        doc.recompute()
        base = featureBase(body)
        for k in range(len(self.start)):
            point = body.newObject("PartDesign::Point", f"Point{k}")
            point.AttachmentSupport = [(base, self.names(base, self.rim(k))[0])]
            point.MapMode = "CenterOfCurvature"
            self.ref(f"point_copy{k}", point, "AttachmentSupport", lambda k=k: self.rim(k), Attached())

    def edit(self, doc):
        """Copy 0 leaves the maker; copy 1 rises onto its place, its bottom rim (the sketch's own
        circle) where copy 0's top rim was, its top rim 5 above."""
        self.setInputs(doc, [doc.Plate, doc.Copy1])
        doc.Copy1.Placement.Base = V(10, 10, 15)
        self.at = {0: None, 1: 10}
        self.z = {1: 20}

    def run(self):
        group = App.ParamGet(SOLVER_GROUP)
        saved = {key: (key in group.GetBools(), group.GetBool(key, True)) for key in self.switches}
        for key, value in self.switches.items():
            group.SetBool(key, value)
        try:
            return super().run()
        finally:
            for key, (had, value) in saved.items():
                if had:
                    group.SetBool(key, value)
                else:
                    group.RemBool(key)


class R5bArrayRaisedOntoTopRim(RaisedCopies):
    """A link array of the pin body (2 elements at x = 10, 20) in a Compound. Element 0 is hidden
    and element 1 rises onto its place by the placement list."""

    maker = "Part::Compound"

    def makeCopies(self, doc):
        array = doc.addObject("App::Link", "Array")
        array.LinkedObject = self.pin
        array.ElementCount = len(self.start)
        array.ShowElement = False
        doc.recompute()
        array.PlacementList = [App.Placement(V(x, 10, 10), App.Rotation()) for x in self.start]
        return [array]

    def edit(self, doc):
        doc.Array.setElementVisible("0", False)
        doc.Array.PlacementList = [
            App.Placement(V(10, 10, 10), App.Rotation()),
            App.Placement(V(10, 10, 15), App.Rotation()),
        ]
        self.at = {0: None, 1: 10}
        self.z = {1: 20}


class R5bArrayRaisedOntoTopRimFused(R5bArrayRaisedOntoTopRim):
    """The same link array in a MultiFuse; element 0 is moved off the plate (to x 2000, y 1000,
    z 500: a free pin, its top rim at z 505) rather than hidden, and element 1 rises onto its place."""

    maker = "Part::MultiFuse"

    def rim(self, k):
        if k == 0 and getattr(self, "far", False):
            # copy 0 still exists, off the plate: its own top rim, or a break
            return OwnOrBroken(edge(center=(2000, 1000, 505), radius=2))
        return super().rim(k)

    def edit(self, doc):
        doc.Array.PlacementList = [
            App.Placement(V(2000, 1000, 500), App.Rotation()),
            App.Placement(V(10, 10, 15), App.Rotation()),
        ]
        self.far = True
        self.at = {0: None, 1: 10}
        self.z = {1: 20}


class R5bBinderRaisedOntoTopRim(RaisedCopies):
    """The copies are two SubShapeBinders of the pin body (each its own maker)."""

    def makeCopies(self, doc):
        copies = []
        for k, x in enumerate(self.start):
            binder = doc.addObject("PartDesign::SubShapeBinder", f"Copy{k}")
            binder.Support = [(self.pin, "")]
            binder.Placement.Base = V(x, 10, 10)
            copies.append(binder)
        doc.recompute()
        return copies


class R5bSameMakerOffRaisedOntoTopRim(RaisedCopies):
    """Round 5's Opus case (two links, copy 1 raised onto copy 0's top rim) with Tier1SameMaker off
    (a comparison switch): otherOriginOf() then asks for no maker."""

    switches = {"Tier1SameMaker": False}


class R5bPinPadReplaced(Scenario):
    """A body's own feature replaced: in the pin body (a 3000 x 2000 x 10 plate pad and a pin pad 5
    high of a circle r = 2 in its own sketch on the plate's top), the pin pad is deleted and a new
    pad of the same sketch, as high, takes its place. A second body on the pin body has a datum on
    the pin's top rim: the new pad's top rim is the same rim, or the reference breaks (the maker
    is gone, the sketch lives)."""

    area = "review-r5b-links"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "X4:4000")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5b"
    TIER = "F"
    REFS = ("top_rim",)

    def rim(self):
        return OwnOrBroken(edge(center=(10, 10, 15), radius=2))

    def build(self, doc):
        part = m.body(doc)
        self.part = part
        plate = m.sketch(doc, "PlateSketch", m.rectangle(0, 0, 3000, 2000), part)
        m.pad(part, plate, 10, "PlatePad")
        self.pinSketch = m.sketch(doc, "PinSketch", [m.circle(10, 10, 2)], part, z=10)
        m.pad(part, self.pinSketch, 5, "PinPad")
        body = m.body(doc)
        body.BaseFeature = part
        doc.recompute()
        base = featureBase(body)
        point = body.newObject("PartDesign::Point", "Point")
        point.AttachmentSupport = [(base, self.names(base, edge(center=(10, 10, 15), radius=2))[0])]
        point.MapMode = "CenterOfCurvature"
        self.ref("top_rim", point, "AttachmentSupport", self.rim, Attached())

    def edit(self, doc):
        part = self.part
        old = doc.PinPad
        part.removeObject(old)
        doc.removeObject(old.Name)
        doc.recompute()
        pad = part.newObject("PartDesign::Pad", "PinPad2")
        pad.Profile = self.pinSketch
        pad.Length = 5
        part.Tip = pad
