# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prline-b3-r1 (P4, FeatureRevolved.cpp seatAxisTouches): a profile edge that touches the
revolve axis inside the edge is split there on the PR, so the face it revolves into becomes two
faces (upper and lower half) while the profile touches the axis, and one face while it doesn't.
An edit that moves the profile onto, or off, the axis is the switch point.

The profile is a "D" in the XZ plane (sketch x, y = global x, z): the left half of a circle of
radius r centred (c, 0) (an arc from (c, r) through (c - r, 0) to (c, -r)) closed by the line
x = c. Revolved 360 degrees about the sketch's V axis (global Z): the line gives a cylinder of
radius c, the arc a round face; at c = r the arc touches the axis at the origin (a pinch, a pole).
References: a SubShapeBinder on the round face(s), a Fillet on the top rim circle (z = r, radius c)
between the cylinder and the round face.

Moved into the corpus by kernel safety 8 (F1): with no base, the revolve touching the axis came out
inside out and S2 stopped it, so the touching builds were errors until the seated face kept its
wire's orientation."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Bound, Filleted, Scenario, V, edge, face, pieces
from PartDesignTests.Scenarios import models as m

XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def _round(f):
    return type(f.Surface).__name__ not in ("Plane", "Cylinder")


class _RevolveTouch(Scenario):
    abstract = True
    area = "revolve"
    CLASSES = ("C",)
    AXES = ("X4:600",)
    ISSUE = "ops#640"
    FOUND_BY = "review prline-b3-r1"
    TIER = "F"
    SIZE = 240
    SCALE = 1.0
    REFS = ("round_faces", "rim_fillet")
    r = 100.0
    c0 = 120.0  # built
    c1 = 100.0  # edited

    def roundFaces(self):
        return pieces(face(where=_round))

    def rim(self):
        r, c = self.s(self.r), self.s(self.c)
        return edge("circle", center=(0, 0, r), radius=c)

    def geometry(self, c):
        r = self.s(self.r)
        arc = Part.ArcOfCircle(Part.Circle(V(c, 0, 0), V(0, 0, 1), r), math.pi / 2, 3 * math.pi / 2)
        line = Part.LineSegment(V(c, -r, 0), V(c, r, 0))
        return [arc, line]

    def build(self, doc):
        self.c = self.c0
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.geometry(self.s(self.c)), body, placement=XZ)
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = profile
        rev.ReferenceAxis = (profile, ["V_Axis"])
        rev.Angle = 360
        doc.recompute()
        binder = doc.addObject("PartDesign::SubShapeBinder", "RoundBinder")
        binder.Support = [(rev, tuple(self.roundFaces().select(rev.Shape)))]
        self.ref("round_faces", binder, "Support", self.roundFaces, Bound())
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (rev, self.names(rev, self.rim()))
        fillet.Radius = self.s(5)
        self.ref("rim_fillet", fillet, "Base", self.rim, Filleted(self.s(5)))
        doc.recompute()

    def edit(self, doc):
        self.c = self.c1
        c, r = self.s(self.c), self.s(self.r)
        sketch = doc.Profile
        geometry = sketch.Geometry
        geometry[0].Center = V(c, 0, 0)
        geometry[1].StartPoint = V(c, -r, 0)
        geometry[1].EndPoint = V(c, r, 0)
        sketch.Geometry = geometry
        doc.recompute()


class RevolveDOntoAxis(_RevolveTouch):
    """Built 20 off the axis (c = 120, r = 100): one round face. The profile moves onto the axis
    (c = 100): every round face (on the PR two halves) is the reference's."""

    abstract = False
    c0, c1 = 120.0, 100.0


class RevolveDOffAxis(_RevolveTouch):
    """Built touching the axis (c = 100, r = 100: on the PR two round faces, both bound). The
    profile moves 20 off the axis (c = 120): the one round face is the reference's."""

    abstract = False
    c0, c1 = 100.0, 120.0


class _GrooveTouch(_RevolveTouch):
    """As _RevolveTouch, but the D is a Groove (360 degrees) in a cylinder of radius 300 about Z,
    z -150..150: the groove's round face (or its two halves on the PR) bounds a pinched cavity
    around the axis. The Fillet is left out (the rim is now an inner edge of a cavity)."""

    abstract = True
    REFS = ("round_faces",)

    def build(self, doc):
        self.c = self.c0
        body = m.body(doc)
        base = m.sketch(doc, "Base", [m.circle(0, 0, self.s(300))], body, z=-self.s(150))
        m.pad(body, base, self.s(300))
        profile = m.sketch(doc, "Profile", self.geometry(self.s(self.c)), body, placement=XZ)
        groove = body.newObject("PartDesign::Groove", "Groove")
        groove.Profile = profile
        groove.ReferenceAxis = (profile, ["V_Axis"])
        groove.Angle = 360
        doc.recompute()
        binder = doc.addObject("PartDesign::SubShapeBinder", "RoundBinder")
        binder.Support = [(groove, tuple(self.roundFaces().select(groove.Shape)))]
        self.ref("round_faces", binder, "Support", self.roundFaces, Bound())
        doc.recompute()


class GrooveDOntoAxis(_GrooveTouch):
    """The groove's D moves from 20 off the axis onto it: every round face is the reference's."""

    abstract = False
    c0, c1 = 120.0, 100.0


class GrooveDOffAxis(_GrooveTouch):
    """The groove's D, built touching the axis, moves 20 off it: the one round face."""

    abstract = False
    c0, c1 = 100.0, 120.0
