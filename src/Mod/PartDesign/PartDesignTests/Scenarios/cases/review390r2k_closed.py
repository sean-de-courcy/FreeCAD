# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2k (ops#468): stop 2 (a gone closed twin's place candidates reserved in the
owner's `exact`) where another reference of the owner moved onto that place and is right there.

The model is review390r2j_closed2.py's: a Pad of a circle r 10, 20 high; a groove (a YZ-plane
circle r 3 at (y 0, z 20), pocketed 24 long, symmetric: a channel along x, x -12..12, walls at
y -3 and y 3). The top rim's crossings with the wall y 3, (+-9.539, 3, 20), are closed-edge twins
on the PR; c_p is the one at x -9.539. c_m is the wall y -3's crossing at (-9.539, -3, 20).
A second Pocket, 1 deep, from a rectangle F (x -1..1, y -8..-7) keeps a later feature.

One edit: the groove's sketch moved by (dx, dy). With (-8, +6) the channel spans x -20..4 and its
walls are at y 3 and 9: the wall that was at y 3 now crosses the rim at (-4.359, 9) (its +x
crossing is past the channel's end, so c_p's twin count drops: renamed on the PR), and the wall
that was at y -3 now crosses at (-9.539, 3), c_p's old place, its +x crossing gone as well.
c_p follows its wall's crossing or breaks; c_m follows its wall's crossing, which now sits at c_p's
old place, or breaks. Neither may take the other's.
"""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
YZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120))
CX = math.sqrt(100 - 9)


class Base(Scenario):
    abstract = True
    AXES = ("M3", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2k"
    TIER = "F"
    SIZE = 20
    SCALE = 1.0
    REFS = ("c_p", "c_m")
    WALL = {"c_p": 3.0, "c_m": -3.0}
    SHIFT = (-8.0, 6.0)
    ONE_OWNER = True
    edited = False

    def at(self, x, y):
        return vertex(V(x * self.scale, y * self.scale, 20 * self.scale))

    def before(self, name):
        return self.at(-CX, self.WALL[name])

    def after(self, name):
        dx, dy = self.SHIFT
        y = self.WALL[name] + dy
        if abs(y) >= 10:
            return OwnOrBroken(self.before(name))  # unreachable here
        x = -math.sqrt(100 - y * y)
        return OwnOrBroken(self.at(x, y))

    def expectation(self, name):
        def expect():
            return self.after(name) if self.edited else self.before(name)

        return expect

    def build(self, doc):
        s = self.scale
        self.edited = False
        body = m.body(doc)
        disk = m.sketch(doc, "Disk", [m.circle(0, 0, 10 * s)], body)
        m.pad(body, disk, 20 * s)
        self.tool = m.sketch(doc, "Tool", [m.circle(0, 20 * s, 3 * s)], body, placement=YZ)
        groove = m.pocket(body, self.tool, 24 * s, "Groove")
        groove.SideType = "Symmetric"
        doc.recompute()
        sk = m.sketch(doc, "Small", m.rectangle(-1 * s, -8 * s, 1 * s, -7 * s), body, z=20 * s)
        pocket = m.pocket(body, sk, 1 * s, "Small")
        doc.recompute()
        subs = [self.names(pocket, self.before(n))[0] for n in self.REFS]
        if self.ONE_OWNER:
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[0])]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subs[1])
            self.ref(self.REFS[0], probe, "AttachmentSupport", self.expectation(self.REFS[0]), Attached())
            self.ref(self.REFS[1], probe, "ExternalGeometry", self.expectation(self.REFS[1]))
        else:
            for name, sub in zip(self.REFS, subs):
                pt = body.newObject("PartDesign::Point", "On" + name)
                pt.AttachmentSupport = [(pocket, sub)]
                pt.MapMode = "CenterOfMass"
                self.ref(name, pt, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket
        doc.recompute()

    def edit(self, doc):
        dx, dy = self.SHIFT
        # the sketch is in the YZ plane: its x is the world y; the placement's base is world
        self.tool.Placement = App.Placement(V(dx * self.scale, dy * self.scale, 0), YZ.Rotation)
        self.edited = True


class R2kClosedOntoGoneTwin(Base):
    """c_p attached, c_m external: c_m's crossing moves onto c_p's old place."""


class R2kClosedOntoGoneTwinSwapped(Base):
    """c_m attached, c_p external."""

    REFS = ("c_m", "c_p")


class R2kClosedOntoGoneTwinTwoOwners(Base):
    """The control: one datum point each."""

    ONE_OWNER = False


class R2kClosedOntoGoneTwinNear(Base):
    """The same with dy 6.05: c_m's crossing lands 0.05 off c_p's old place."""

    SHIFT = (-8.0, 6.05)


class R2kClosedOntoGoneTwinNearSwapped(R2kClosedOntoGoneTwinNear):
    REFS = ("c_m", "c_p")


class R2kClosedStayTwinGone(Base):
    """dx -8 only: both walls stay (y 3 and -3), their +x crossings past the channel's end, so
    c_p's twin count drops (renamed on the PR) while its element stays at its place. c_m stays
    too. c_p follows (its place) or breaks; c_m holds its place."""

    SHIFT = (-8.0, 0.0)


class R2kClosedStayTwinGoneSwapped(R2kClosedStayTwinGone):
    REFS = ("c_m", "c_p")
