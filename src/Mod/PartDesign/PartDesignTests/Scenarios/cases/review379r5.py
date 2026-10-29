# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases for fork PR 379 round 5 (the rebase onto fork PR 392's link copies): where D1's
twin rule (isTwinName, the twin clause, twinPick, the order test, XP) meets link copies.

The pin is a PartDesign Body: a pad 20 x 10 x 5 (at scale 1) with a through pocket of a circle
r = 1 at (10, 0.5), whose cylinder crosses the top front edge (y = 0, z = 5) at two vertices,
x = 10 -+ 0.866, told apart by the Index of their names only (D1's twins). Two App::Links to the
body, Copy0 at x offset 0 and Copy1 at offset 40, and a far Plate, in a Part::MultiFuse. A body
on the fuse has datum points on copy k's two crossings. Copy k's points must follow copy k's
crossings, or break where copy k is gone; never land on another copy's.
`LONG`: the Plate is 4000 long, so d_max (1 % of the diagonal, ~40) holds the twin 1.732 away
and tier 3's gap test refuses: XP decides.
"""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Scenario,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
RADIUS = 1.0


def featureBase(body):
    return next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")


class LinkedTwins(Scenario):
    abstract = True
    area = "review-r5-links"
    CLASSES = ("A", "D")
    AXES = ("M5", "E1")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5"
    TIER = "F"
    REFS = ("c0_left", "c0_right", "c1_left", "c1_right")
    LONG = False
    cx, cy = 10.0, 0.5
    offsets = (0.0, 40.0)

    def span(self):
        return math.sqrt(RADIUS**2 - self.cy**2)

    def crossing(self, k, side):
        off = self.at.get(k)
        if off is None:
            return BROKEN
        return vertex(at=(off + self.cx + side * self.span(), 0, 5))

    def build(self, doc):
        self.at = dict(enumerate(self.offsets))
        pin = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), pin)
        m.pad(pin, profile, 5)
        self.hole = m.sketch(doc, "Hole", [m.circle(self.cx, self.cy, RADIUS)], pin)
        pocket = pin.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 1
        pocket.Midplane = True
        length = 4000 if self.LONG else 40
        m.box(doc, "Plate", (length, 5, 5), at=(0, 30, 0))
        for k, x in enumerate(self.offsets):
            link = doc.addObject("App::Link", f"Copy{k}")
            link.LinkedObject = pin
            link.Placement.Base = V(x, 0, 0)
        fuse = doc.addObject("Part::MultiFuse", "Maker")
        fuse.Shapes = [doc.Copy0, doc.Copy1, doc.Plate]
        body = m.body(doc)
        body.BaseFeature = fuse
        doc.recompute()
        base = featureBase(body)
        for k in (0, 1):
            for name, side in (("left", -1), ("right", 1)):
                point = body.newObject("PartDesign::Point", f"P{k}{name}")
                point.AttachmentSupport = [(base, self.names(base, self.crossing(k, side))[0])]
                point.MapMode = "Vertex"
                self.ref(
                    f"c{k}_{name}",
                    point,
                    "AttachmentSupport",
                    lambda k=k, side=side: self.crossing(k, side),
                    Attached(),
                )

    def moveCircle(self, x, y):
        self.hole.moveGeometry(0, 3, V(x, y, 0), False)
        self.cx, self.cy = x, y

    def removeCopy0(self, doc):
        doc.Maker.Shapes = [doc.Copy1, doc.Plate]
        self.at[0] = None

    def moveCopy1(self, doc, x):
        doc.Copy1.Placement.Base = V(x, 0, 0)
        self.at[1] = x


class R5LinkedTwinSeam(LinkedTwins):
    """The hole's y 0.5 -> 0 in the pin: in both copies the right crossing becomes the
    cylinder's seam vertex (D1's twin clause), then back."""

    steps = ("move", "back")

    def move(self, doc):
        self.home = (self.cx, self.cy)
        self.moveCircle(self.cx, 0.0)

    def back(self, doc):
        self.moveCircle(*self.home)


class R5LinkedTwinSeamLong(R5LinkedTwinSeam):
    LONG = True


class R5LinkedCopyGoneTwinOntoPlace(LinkedTwins):
    """Copy 0 leaves the fuse; copy 1 moves to offset 1.732, its left crossing exactly where
    copy 0's right crossing was. Copy 0's points break; copy 1's follow copy 1."""

    def edit(self, doc):
        self.removeCopy0(doc)
        self.moveCopy1(doc, 2 * self.span())


class R5LinkedCopyGoneTwinOntoPlaceLong(R5LinkedCopyGoneTwinOntoPlace):
    LONG = True


class R5LinkedCopyGoneOntoPlace(LinkedTwins):
    """Copy 0 leaves the fuse; copy 1 moves onto copy 0's place."""

    def edit(self, doc):
        self.removeCopy0(doc)
        self.moveCopy1(doc, 0.0)


class R5LinkedCopyGoneOntoPlaceLong(R5LinkedCopyGoneOntoPlace):
    LONG = True


class R5LinkedSeamCopyGoneOntoPlace(LinkedTwins):
    """The hole's y 0.5 -> 0 (the right crossings become seam vertices), copy 0 leaves the fuse
    and copy 1 moves onto copy 0's place."""

    def edit(self, doc):
        self.moveCircle(self.cx, 0.0)
        self.removeCopy0(doc)
        self.moveCopy1(doc, 0.0)


class R5LinkedSeamCopyGoneOntoPlaceLong(R5LinkedSeamCopyGoneOntoPlace):
    LONG = True


class R5LinkedCopiesSwapped(LinkedTwins):
    """The two links trade placements (copy 0 to 40, copy 1 to 0): each copy's points follow
    their copy, or break."""

    def edit(self, doc):
        doc.Copy0.Placement.Base = V(40, 0, 0)
        doc.Copy1.Placement.Base = V(0, 0, 0)
        self.at = {0: 40.0, 1: 0.0}


# Rims: copy 1's bottom rim moved onto copy 0's top rim (both made from the pin's one circle)


class PinRims(Scenario):
    """K8b's model with a PartDesign pin (a pad 5 of a circle r = 2), two links on a 40 x 20 x 10
    box (or a 4000 long one, LONG) in a MultiFuse; datum points on each copy's top rim."""

    abstract = True
    area = "review-r5-links"
    CLASSES = ("A", "D")
    AXES = ("M5", "E1", "E4")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r5"
    TIER = "F"
    REFS = ("point_copy0", "point_copy1")
    LONG = False

    def rim(self, k):
        place = self.at.get(k)
        if place is None:
            return BROKEN
        x, z = place
        return edge(center=(x, 10, z + 5), radius=2)

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", (4000 if self.LONG else 40, 20, 10))
        pin = m.body(doc)
        sketch = m.sketch(doc, "PinSketch", [m.circle(0, 0, 2)], pin)
        m.pad(pin, sketch, 5, "PinPad")
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
        for k in (0, 1):
            point = body.newObject("PartDesign::Point", f"Point{k}")
            point.AttachmentSupport = [(base, self.names(base, self.rim(k))[0])]
            point.MapMode = "CenterOfCurvature"
            self.ref(f"point_copy{k}", point, "AttachmentSupport", lambda k=k: self.rim(k), Attached())


class R5PinBottomRimOntoTopRim(PinRims):
    """Copy 0 leaves the fuse; copy 1 moves to (10, 10, 15): its bottom rim lies exactly where
    copy 0's top rim was (copy 1 floats 5 above the box). Copy 0's point breaks."""

    def edit(self, doc):
        doc.Fuse.Shapes = [doc.Plate, doc.Copy1]
        doc.Copy1.Placement.Base = V(10, 10, 15)
        self.at = {0: None, 1: (10, 15)}


class R5PinBottomRimOntoTopRimLong(R5PinBottomRimOntoTopRim):
    LONG = True


class R5TwoPinBodiesBottomRimOntoTopRimLong(PinRims):
    """The control without links: two pin bodies, each with its own sketch, in place of the two
    copies. Pin 0 leaves the fuse; pin 1 moves to (10, 10, 15), its bottom rim where pin 0's top
    rim was. Pin 0's point breaks (the pick lost the old name's sketch source)."""

    LONG = True

    def build(self, doc):
        self.at = {0: (10, 10), 1: (20, 10)}
        m.box(doc, "Plate", (4000, 20, 10))
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
        for k in (0, 1):
            point = body.newObject("PartDesign::Point", f"Point{k}")
            point.AttachmentSupport = [(base, self.names(base, self.rim(k))[0])]
            point.MapMode = "CenterOfCurvature"
            self.ref(f"point_copy{k}", point, "AttachmentSupport", lambda k=k: self.rim(k), Attached())

    def edit(self, doc):
        doc.Fuse.Shapes = [doc.Plate, self.pins[1]]
        self.pins[1].Placement.Base = V(10, 10, 15)
        self.at = {0: None, 1: (10, 15)}
