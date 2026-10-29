# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr379-r5s: K8b's link-copy models on a big plate, so that tier 3's gap test (d_max = 1 % of
the diagonal, ~36 mm) refuses on `integration` and XP (the exact place) decides on the PR.

A 3000 x 2000 x 10 plate, a pin r = 2, 5 high, copies standing on the plate at (x, 10, 10); a Body on
the maker's result has datum points at the centres of the copies' top rims (z = 15). The pin's
bottom rim, 5 mm below the top rim, lies within d_max, so the gap test refuses wherever the top rim
is the nearest: only XP can take the element at the place.
"""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    Attached,
    BROKEN,
    OwnOrBroken,
    Scenario,
    edge,
    face,
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


class BigCopies(Scenario):
    abstract = True
    area = "link-copies"
    CLASSES = ("D",)
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5s"
    TIER = "F"
    AXES = ("M5", "E1", "E4", "X4:4000")
    maker = "Part::MultiFuse"
    start = (10, 20)
    REFS = ("point_copy0", "point_copy1")
    plate = (3000, 2000, 10)

    def rim(self, k):
        x = self.at.get(k)
        return BROKEN if x is None else edge(center=(x, 10, 15), radius=2)

    def makePin(self, doc):
        pin = doc.addObject("Part::Cylinder", "Pin")
        pin.Radius, pin.Height = 2, 5
        return pin

    def makeCopy(self, doc, k, x):
        link = doc.addObject("App::Link", f"Copy{k}")
        link.LinkedObject = doc.Pin
        link.Placement.Base = V(x, 10, 10)
        return link

    def setInputs(self, doc, objs):
        if self.maker == "Part::MultiFuse":
            doc.Maker.Shapes = objs
        else:
            doc.Maker.Links = objs

    def inputs(self, doc):
        return [doc.Plate] + [doc.getObject(f"Copy{k}") for k in range(len(self.start))]

    def build(self, doc):
        self.at = dict(enumerate(self.start))
        m.box(doc, "Plate", self.plate)
        self.makePin(doc)
        for k, x in enumerate(self.start):
            self.makeCopy(doc, k, x)
        doc.addObject(self.maker, "Maker")
        self.setInputs(doc, self.inputs(doc))
        self.refer(doc)

    def refer(self, doc):
        body = m.body(doc)
        body.BaseFeature = doc.Maker
        doc.recompute()
        base = featureBase(body)
        for k in range(len(self.start)):
            point = datumPoint(body, base, self.names(base, self.rim(k))[0], f"Point{k}")
            self.ref(f"point_copy{k}", point, "AttachmentSupport", lambda k=k: self.rim(k), Attached())

    def removeCopy0(self, doc):
        self.setInputs(doc, [o for o in self.inputs(doc) if o.Name != "Copy0"])
        self.at[0] = None


class BigLinkPinRemovedNeighbourMoved(BigCopies):
    """Link 0 leaves the fuse and link 1 moves to (10, 10): copy 0's point must break."""

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


class BigLinkPinRemovedNeighbourMovedCompound(BigLinkPinRemovedNeighbourMoved):
    maker = "Part::Compound"


class BigLinkCopyRemoved(BigCopies):
    """Only link 0 leaves the fuse. Copy 0's point must break; copy 1's stays."""

    def edit(self, doc):
        self.removeCopy0(doc)


class BigLinkSwappedPlacements(BigCopies):
    """Copies 0 and 1 trade places; each follows its copy or breaks."""

    def edit(self, doc):
        doc.Copy0.Placement.Base = V(20, 10, 10)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at = {0: 20, 1: 10}


class BigPinAndLinkNeighbourMoved(BigCopies):
    """The pin itself is copy 0, a link to it copy 1. The pin leaves, the link moves onto its place."""

    def makeCopy(self, doc, k, x):
        if k == 0:
            doc.Pin.Placement.Base = V(x, 10, 10)
            return doc.Pin
        return super().makeCopy(doc, k, x)

    def inputs(self, doc):
        return [doc.Plate, doc.Pin, doc.Copy1]

    def removeCopy0(self, doc):
        self.setInputs(doc, [doc.Plate, doc.Copy1])
        self.at[0] = None

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


class BigScaleAndLinkNeighbourMoved(BigCopies):
    """Copy 0 is a Scale of the pin (CPY;1), copy 1 a link (CPY;L). The Scale leaves; the link moves
    onto its place."""

    def makeCopy(self, doc, k, x):
        if k == 0:
            scale = doc.addObject("Part::Scale", "Copy0")
            scale.Base = doc.Pin
            scale.Uniform = True
            scale.UniformScale = 1
            scale.Placement.Base = V(x, 10, 10)
            return scale
        return super().makeCopy(doc, k, x)

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


class BigLinkArrayFirstDroppedMoved(BigCopies):
    """A link array, 3 elements at x = 8, 20, 32. Element 0 is hidden and element 1 is moved onto
    its place (by the placement list)."""

    maker = "Part::Compound"
    start = (8, 20, 32)
    REFS = ("point_copy0", "point_copy1", "point_copy2")

    def build(self, doc):
        self.at = dict(enumerate(self.start))
        m.box(doc, "Plate", self.plate)
        self.makePin(doc)
        array = doc.addObject("App::Link", "Array")
        array.LinkedObject = doc.Pin
        array.ElementCount = len(self.start)
        array.ShowElement = False
        doc.recompute()
        array.PlacementList = [App.Placement(V(x, 10, 10), App.Rotation()) for x in self.start]
        doc.addObject(self.maker, "Maker")
        self.setInputs(doc, [doc.Plate, array])
        self.refer(doc)

    def edit(self, doc):
        doc.Array.setElementVisible("0", False)
        doc.Array.PlacementList = [
            App.Placement(V(x, 10, 10), App.Rotation()) for x in (8, 8, 32)
        ]
        self.at = {0: None, 1: 8, 2: 32}


class BigBodyPin(BigCopies):
    """The pin a PartDesign Body (a pad of a circle in PinSketch): the sketch can be drawn again."""

    abstract = True

    def makePin(self, doc):
        pinBody = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pinBody)
        m.pad(pinBody, sketch, 5, "PinPad")
        doc.recompute()
        self.pinBody = pinBody
        return pinBody

    def makeCopy(self, doc, k, x):
        link = doc.addObject("App::Link", f"Copy{k}")
        link.LinkedObject = self.pinBody
        link.Placement.Base = V(x, 10, 10)
        return link

    def redraw(self, doc):
        import Part

        sketch = doc.PinSketch
        sketch.delGeometry(0)
        sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 2))


class BigBodyPinRemovedNeighbourMoved(BigBodyPin):
    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


class BigBodyPinRedrawnThenCut(BigBodyPin):
    """The pin's circle is drawn again in place (both copies' rims are renamed), then copy 0 leaves
    and copy 1 moves onto its place."""

    steps = ("redraw", "cut")

    def redraw(self, doc):
        super().redraw(doc)

    def cut(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10


class BigBodyPinCutAndRedrawn(BigBodyPin):
    """Copy 0 leaves, copy 1 moves onto its place, and the pin's circle is drawn again, in one edit."""

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 10)
        self.at[1] = 10
        self.redraw(doc)


class BigBodyPinRedrawnThenCutBoth(BigBodyPin):
    """The pin's circle is drawn again, then copy 0 leaves (copy 1 stays at 20)."""

    steps = ("redraw", "cut")

    def cut(self, doc):
        self.removeCopy0(doc)


class BigBodyPinRaisedOntoTopRim(BigBodyPin):
    """Copy 0 leaves the fuse and copy 1 moves up by the pin's height onto its place: copy 1's bottom
    rim (the sketch's own circle) lies where copy 0's top rim was, its top rim 5 mm above, within
    d_max. Copy 0's point must break; copy 1's follows its top rim."""

    def rim(self, k):
        x = self.at.get(k)
        z = getattr(self, "z", {}).get(k, 15)
        return BROKEN if x is None else edge(center=(x, 10, z), radius=2)

    def edit(self, doc):
        self.removeCopy0(doc)
        doc.Copy1.Placement.Base = V(10, 10, 15)
        self.at[1] = 10
        self.z = {1: 20}


class BigBodyPinRaisedOntoTopRimMedium(BigBodyPinRaisedOntoTopRim):
    """The same on a 600 x 400 x 10 plate (d_max ~ 7 mm)."""

    plate = (600, 400, 10)
    AXES = ("M5", "E1", "E4", "X4:600")


class BigBodyPinRaisedOntoTopRimSmall(BigBodyPinRaisedOntoTopRim):
    """The same on the 40 x 20 x 10 plate (d_max 0.5 mm: tier 3's gap is clear on both builds)."""

    plate = (40, 20, 10)
    AXES = ("M5", "E1", "E4", "X4:60")


class BigLinkPinRaisedOntoTopRim(BigBodyPinRaisedOntoTopRim):
    """A Part::Cylinder pin (primitive names)."""

    def makePin(self, doc):
        return BigCopies.makePin(self, doc)

    def makeCopy(self, doc, k, x):
        return BigCopies.makeCopy(self, doc, k, x)


class BigScaleRaisedOntoTopRim(BigBodyPinRaisedOntoTopRim):
    """Copy 0 is a Scale (CPY;1), copy 1 a link to the body pin."""

    def makeCopy(self, doc, k, x):
        if k == 0:
            scale = doc.addObject("Part::Scale", "Copy0")
            scale.Base = self.pinBody
            scale.Uniform = True
            scale.UniformScale = 1
            scale.Placement.Base = V(x, 10, 10)
            return scale
        return super().makeCopy(doc, k, x)
