# SPDX-License-Identifier: LGPL-2.1-or-later
"""Probes of fork PR 384, round 1 (class E, E1): the build-order slots and the insertion of new
geometry across two face links of one sketch. Kept as cases; they pass on the PR."""

import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face, faceNormal, pieces
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


class CircleOnLinkLine(Outcome):
    """The sketch computes; the circle's PointOnObject names a projected line of the link whose
    reference names `face` (by the geometry's Ref), on x = value, and the circle's centre is
    on it."""

    def __init__(self, value):
        self.value = value

    def compare(self, scenario, consumer, target, expectation):
        if not consumer.isValid():
            return False, consumer.getStatusString()
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        geo = consumer.ExternalGeo[-constraint.Second - 1]
        refs = []  # the links' keys, in ExternalGeo's order
        for g in consumer.ExternalGeo[2:]:
            ref = Sketcher.ExternalGeometryFacade(g).Ref
            if ref not in refs:
                refs.append(ref)
        ref = Sketcher.ExternalGeometryFacade(geo).Ref
        if refs.index(ref) != scenario.link:
            return False, f"the constraint is on a line of link {refs.index(ref)}, not {scenario.link}"
        ends = (geo.StartPoint, geo.EndPoint)
        if not all(abs(p.x - self.value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(centre.x - self.value) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class ExternalTwoFaceLinksCornerCut(Scenario):
    """The 20 x 20 square padded 10 high; a sketch at z = -5 projects the pad's top face, then
    its bottom face (two links, the top's first in ExternalGeo); a circle on the bottom link's
    left line. A 5 x 5 corner cut at (20, 20): both links gain a line before their left line,
    the top link's inserted before the bottom link's slots. The circle stays on the bottom
    link's left line."""

    area = "external geometry"
    CLASSES = ("E",)
    AXES = ("M8", "E1")
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r1"
    TIER = "F"
    REFS = ("circle_on_bottom_x0",)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    link = 1

    def bottomFace(self):
        return face("plane", normal=-Z, through=(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "Below", [], body, z=-5)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        bottom = self.names(pad, self.bottomFace())[0]
        sketch.addExternal(pad.Name, bottom)
        doc.recompute()
        geos = list(enumerate(sketch.ExternalGeo))
        bottomRef = Sketcher.ExternalGeometryFacade(geos[-1][1]).Ref
        left = [
            -i - 1 for i, g in geos
            if i >= 2 and hasattr(g, "StartPoint")
            and Sketcher.ExternalGeometryFacade(g).Ref == bottomRef
            and abs(g.StartPoint.x) < TOL and abs(g.EndPoint.x) < TOL
        ]
        circle = sketch.addGeometry(m.circle(0, 5, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, left[0]))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref("circle_on_bottom_x0", sketch, "ExternalGeometry", self.bothFaces,
                 CircleOnLinkLine(0))

    def bothFaces(self):
        return pieces(face("plane", where=lambda f: abs(abs(faceNormal(f).z) - 1) < 1e-9))

    def edit(self, doc):
        m.setLines(doc.Profile, {1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        doc.Profile.addGeometry(m.polyline([(20, 15), (15, 20)]), False)


class ExternalFaceCornerCut4mThenNotch(Scenario):
    """Composed, at 4 m: a 4000 x 4000 square padded 2000; a sketch projects the top face, a
    circle on the left line. First a 1000 x 1000 corner cut at (4000, 4000), then a notch in
    the front edge (1600 .. 2400, 600 deep): lines before the left line twice."""

    area = "external geometry"
    CLASSES = ("E",)
    AXES = ("M8", "E1", "X4:4000")
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r1"
    TIER = "F"
    REFS = ("circle_on_bottom_x0",)
    steps = ("cut", "notch")
    link = 0

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 2000))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 4000, 4000), body)
        pad = m.pad(body, profile, 2000)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        top = self.names(pad, self.topFace())[0]
        sketch.addExternal(pad.Name, top)
        doc.recompute()
        left = [
            -i - 1 for i, g in enumerate(sketch.ExternalGeo)
            if i >= 2 and abs(g.StartPoint.x) < TOL and abs(g.EndPoint.x) < TOL
        ]
        circle = sketch.addGeometry(m.circle(0, 1000, 200), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, left[0]))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 200))
        self.ref("circle_on_bottom_x0", sketch, "ExternalGeometry", self.topFace,
                 CircleOnLinkLine(0))

    def cut(self, doc):
        m.setLines(doc.Profile, {1: ((4000, 0), (4000, 3000)), 2: ((3000, 4000), (0, 4000))})
        doc.Profile.addGeometry(m.polyline([(4000, 3000), (3000, 4000)]), False)

    def notch(self, doc):
        m.setLines(doc.Profile, {0: ((0, 0), (1600, 0))})
        doc.Profile.addGeometry(
            m.polyline([(1600, 0), (1600, 600), (2400, 600), (2400, 0), (4000, 0)]), False
        )
