# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6ks (fork PR 383, f54fb67fff, decision 198): the in-frame read of a closed spine with a
turned profile frame stands where every stored name FOUND on the spine lies at its carried place. A
stored name that is no longer on the spine is skipped, so a spine whose lines were ALL drawn anew
passes with no name compared at all. Scalene quadrilateral A(0,0) P1(4,22) P2(30,26) P3(24,2) in the XZ
plane (sketch x = X, y = Z), 2 x 2 square profile in the XY plane centred on A. Edit, one recompute:
the quadrilateral mirrored about the sketch's y axis (line 0 A -> P3', each line keeping its side), every
line drawn anew, and the profile reparameterised half a turn (its placement turns about Z, its lines drawn
back: the same square in the body). The placement frame's half turn carries the stored loop exactly onto
the mirrored one. References: datum planes on each leg's front face (y = -1). Each stays at its leg's
front face or breaks; integration breaks (the old lines are gone), the PR resolves to a leg's BACK face."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


class QuadMirroredAllRedrawnProfileReparameterised180(Scenario):
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E2", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6ks"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = ("leg0", "leg1", "leg2", "leg3")
    P0 = ((0, 0), (4, 22), (30, 26), (24, 2))
    mirrored = False

    def corners(self):
        pts = [(-x if self.mirrored else x, z) for (x, z) in self.P0]
        if self.mirrored:  # each line keeps its side: line 0 A -> P3', line 1 P3' -> P2', ...
            pts = [pts[0]] + pts[:0:-1]
        return [V(self.s(x), self.s(z), 0) for (x, z) in pts]

    def front(self, i):
        def predicate():
            c = self.corners()
            a, b = c[i], c[(i + 1) % len(c)]
            mid = V((a.x + b.x) / 2, -self.s(1), (a.y + b.y) / 2)
            return face("plane", normal=V(0, -1, 0), contains=mid)

        return predicate

    def lines(self):
        c = self.corners()
        return [Part.LineSegment(c[i], c[(i + 1) % len(c)]) for i in range(len(c))]

    def build(self, doc):
        body = m.body(doc)
        self.path = m.sketch(doc, "Path", self.lines(), body, placement=XZ)
        one = self.s(1)
        self.profile = m.sketch(doc, "Profile", m.rectangle(-one, -one, one, one), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        made = {}
        for name in self.REFS:
            predicate = self.front(int(name[3]))
            obj = body.newObject("PartDesign::Plane", name)
            obj.MapMode = "FlatFace"
            obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        self.mirrored = True
        self.path.Geometry = self.lines()  # every line drawn anew: new IDs
        back = App.Rotation(V(0, 0, 1), -180)
        g = self.profile.Geometry
        for line in g:
            s, e = back.multVec(V(line.StartPoint)), back.multVec(V(line.EndPoint))
            line.StartPoint, line.EndPoint = V(1e3, 1e3, 0), V(2e3, 2e3, 0)
            line.StartPoint, line.EndPoint = s, e
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 180))
