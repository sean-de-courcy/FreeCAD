# SPDX-License-Identifier: LGPL-2.1-or-later

"""Review pr1114-r1 (ops#1114): a fillet on a pocket floor whose loops are a D outline (a straight
wall meeting an arc wall concave toward the floor: a reflex corner with a circle) and an
elliptical post's foot. Designed geometry. References: the fillet's own selection, and binders on
the post's round and on the chord's round, after the post moves on the floor."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Bound, Filleted, Scenario, edge, face, pieces
from PartDesignTests.Scenarios import models as m

V = App.Vector


class FilletedAsSet(Filleted):
    def compare(self, scenario, consumer, target, expectation):
        self.radius = float(consumer.Radius)
        return super().compare(scenario, consumer, target, expectation)


class ReflexLoopAndPostMoved(Scenario):
    """A block 120 x 100 x 13 with a D pocket 10 deep: the disc R 40 about the z axis kept on the
    side y >= d of the chord y = d (floor angle acos(d / 40) at the two inside corners), and an
    elliptical post (semi-axes 6, 3, centre (0, cy)) padded 10 from the floor. Fillet r 2 on every
    floor edge (the D's chord and arc, the post's foot). Integration refuses (the construction
    does not cover the ellipse); with ops#1114 the D loop and the post's loop are rounded in turn.
    The edit moves the post 5 toward the chord (its band stays 3 clear of the chord's band)."""

    area = "dress-ups"
    CLASSES = ("none",)
    AXES = ("M1", "E2")
    ISSUE = "ops#1114"
    FOUND_BY = "review pr1114-r1"
    TIER = "F"
    REFS = ("fillet_edges", "binder_post_round", "binder_chord_round")
    d = -3.0
    cy = 20.0
    after = 15.0
    radius = 2.0

    def floorEdge(self, e):
        bb = e.BoundBox
        return (
            abs(bb.ZMin - 3) < 1e-6
            and abs(bb.ZMax - 3) < 1e-6
            and bb.XMax < 41
            and bb.XMin > -41
            and bb.YMin > self.d - 1e-6
        )

    def picked(self):
        return pieces(edge(where=self.floorEdge))

    def postRound(self):
        cy, r = self.cy, self.radius

        def test(f):
            bb = f.BoundBox
            return (
                not isinstance(f.Surface, Part.Plane)
                and abs(bb.ZMin - 3) < 1e-6
                and abs(bb.ZMax - 3 - r) < 1e-6
                and abs(bb.XMin + 6 + r) < 1e-3
                and abs(bb.YMin - (cy - 3 - r)) < 1e-3
            )

        return face(where=test)

    def chordRound(self):
        d, r = self.d, self.radius

        def test(f):
            s = f.Surface
            return (
                isinstance(s, Part.Cylinder)
                and abs(s.Radius - r) < 1e-6
                and abs(abs(s.Axis.x) - 1) < 1e-9
                and abs(s.Center.y - (d + r)) < 1e-6
                and abs(s.Center.z - (3 + r)) < 1e-6
            )

        return face(where=test)

    def build(self, doc):
        body = m.body(doc)
        block = m.pad(body, m.sketch(doc, "Block", m.rectangle(-60, -50, 60, 50), body), 13, "Block")
        xs = math.sqrt(40 * 40 - self.d * self.d)
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 40)
        a0 = math.atan2(self.d, xs)
        a1 = math.pi - a0
        outline = [
            Part.ArcOfCircle(circle, a0, a1),
            Part.LineSegment(V(-xs, self.d, 0), V(xs, self.d, 0)),
        ]
        pocket = m.pocket(body, m.sketch(doc, "D", outline, body, z=13), 10)
        post = Part.Ellipse(V(6, self.cy, 0), V(0, self.cy + 3, 0), V(0, self.cy, 0))
        sk = m.sketch(doc, "Post", [post], body, z=3)
        m.pad(body, sk, 10, "PostPad")
        doc.recompute()
        base = doc.PostPad
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, self.picked().select(base.Shape))
        fillet.Radius = self.radius
        doc.recompute()
        self.ref("fillet_edges", fillet, "Base", self.picked, FilletedAsSet(self.radius))
        if "binder_post_round" not in self.REFS:
            return
        b1 = doc.addObject("PartDesign::SubShapeBinder", "PostRound")
        b1.Support = [(fillet, tuple(self.names(fillet, self.postRound())))]
        b2 = doc.addObject("PartDesign::SubShapeBinder", "ChordRound")
        b2.Support = [(fillet, tuple(self.names(fillet, self.chordRound())))]
        self.ref("binder_post_round", b1, "Support", self.postRound, Bound())
        self.ref("binder_chord_round", b2, "Support", self.chordRound, Bound())

    def edit(self, doc):
        doc.Post.Placement = App.Placement(V(0, self.after - self.cy, 3), App.Rotation())
        self.cy = self.after


class ReflexLoopAndPostMovedStudiosForm(ReflexLoopAndPostMoved):
    """The same at d 2 (floor angle 87.13, NS88 Labyrinth #18's form), the fillet's selection only:
    the split's order check (roundCoveredSplit, allowance 1e-9 of the body's volume, 1.33e-4 mm3
    here) refuses the construction's corner built on the two bases, which differ by 1.34e-4 mm3
    in volume (review pr1114-r1). Expected: the fillet builds."""

    d = 2.0
    REFS = ("fillet_edges",)


class ReflexLoopAndPostMovedRightAngle(ReflexLoopAndPostMovedStudiosForm):
    """The same at d 0 (floor angle 90 degrees): the two orders differ by 1.3e-3 mm3."""

    d = 0.0
